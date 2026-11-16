import hashlib
import time

import pytest
import requests

from migration_storage import B2Client, B2Error


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.trust_env = True
        self.before_response = None

    def request(self, method, url, **kwargs):
        captured = dict(kwargs)
        if hasattr(kwargs.get("data"), "read"):
            captured["uploaded_bytes"] = kwargs["data"].read()
            kwargs["data"].seek(0)
        self.calls.append((method, url, captured))
        if self.before_response:
            self.before_response(method, url, kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def auth_response(allowed_buckets=None):
    return Response(
        {
            "accountId": "account-id",
            "authorizationToken": "account-token-secret",
            "apiInfo": {
                "storageApi": {
                    "apiUrl": "https://api.example",
                    "downloadUrl": "https://download.example",
                    "allowed": {"buckets": allowed_buckets},
                }
            },
        }
    )


def listing(files, next_file_name=None):
    return Response({"files": files, "nextFileName": next_file_name})


def empty_unfinished():
    return Response({"files": [], "nextFileId": None})


def uploaded_file(key, data, *, multipart=False):
    result = {
        "fileName": key,
        "contentLength": len(data),
        "contentSha1": "none" if multipart else hashlib.sha1(data).hexdigest(),
    }
    if multipart:
        result["fileInfo"] = {"large_file_sha1": hashlib.sha1(data).hexdigest()}
    return Response(result)


def uploaded_part(data, part_number):
    return Response(
        {
            "partNumber": part_number,
            "contentLength": len(data),
            "contentSha1": hashlib.sha1(data).hexdigest(),
        }
    )


def single_upload_responses(data, key):
    return [
        auth_response([{"id": "bucket-id", "name": "media"}]),
        listing([]),
        Response(
            {
                "uploadUrl": "https://upload.example",
                "authorizationToken": "upload-token",
            }
        ),
        uploaded_file(key, data),
    ]


def disable_retries(monkeypatch):
    monkeypatch.setattr("migration_storage.UPLOAD_RETRIES", 0)


def test_uploads_unchanged_bytes_and_escapes_unicode_key(tmp_path, monkeypatch):
    data = b"unchanged\x00bytes"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    key = "folder/caf\u00e9/\u03b2.bin"
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    session = FakeSession(single_upload_responses(data, key))
    client = B2Client("id", "key", session=session)
    client.ensure_file(source, "media", key)
    upload = session.calls[-1]
    assert upload[2]["uploaded_bytes"] == data
    assert upload[2]["headers"]["X-Bz-File-Name"] == "folder/caf%C3%A9/%CE%B2.bin"
    assert upload[2]["headers"]["X-Bz-Content-Sha1"] == hashlib.sha1(data).hexdigest()
    assert session.trust_env is False
    assert all(call[2]["allow_redirects"] is False for call in session.calls)
    assert sleep_calls == []


def test_single_upload_reports_read_bytes_before_confirmation_and_verified_finish(
    tmp_path,
):
    data = b"streamed bytes"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    events = []

    class ChunkedSession(FakeSession):
        def request(self, method, url, **kwargs):
            if method == "POST" and url == "https://upload.example":
                stream = kwargs["data"]
                chunks = [stream.read(size) for size in (4, 4, 4, 4)]
                stream.seek(0)
                assert stream.read(5) == data[:5]
                self.calls.append(
                    (method, url, {**kwargs, "uploaded_bytes": b"".join(chunks)})
                )
                self.before_response(method, url, kwargs)
                return next(self.responses)
            return super().request(method, url, **kwargs)

    session = ChunkedSession(single_upload_responses(data, "key"))
    order = []

    def record(event):
        events.append(event)
        order.append(event)

    session.before_response = lambda method, url, _kwargs: (
        order.append("upload-response")
        if method == "POST" and url == "https://upload.example"
        else None
    )
    B2Client("id", "key", session=session).ensure_file(
        source, "media", "key", progress=lambda *event: record(event)
    )
    uploaded = next(i for i, event in enumerate(events) if event[0] == "uploaded")
    streamed = [event[1] for event in events if event[0] == "uploading"]
    assert streamed == sorted(set(streamed))
    assert streamed == [0, 4, 8, 12, len(data)]
    assert all(0 <= count <= len(data) for count in streamed)
    assert order.index(("uploading", len(data), len(data))) < order.index(
        "upload-response"
    )
    assert order.index("upload-response") < order.index(events[uploaded])
    assert session.calls[-1][2]["uploaded_bytes"] == data


def test_failed_upload_gets_five_retries_with_30_second_gaps(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"retry payload")
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)

    class AlwaysFailSession:
        trust_env = True

        def __init__(self):
            self.uploads = 0

        def request(self, method, url, **kwargs):
            if url.endswith("b2_authorize_account"):
                return auth_response([{"id": "bucket-id", "name": "media"}])
            if url.endswith("b2_list_file_names"):
                return listing([])
            if url.endswith("b2_get_upload_url"):
                return Response(
                    {"uploadUrl": "https://upload.example", "authorizationToken": "t"}
                )
            if url == "https://upload.example":
                self.uploads += 1
                raise requests.ConnectionError("synthetic upload failure")
            pytest.fail(f"unexpected synthetic request: {method} {url}")

    session = AlwaysFailSession()
    with pytest.raises(B2Error):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")

    assert session.uploads == 6
    assert sleep_calls == [30, 30, 30, 30, 30]


def test_partial_single_failure_reopens_file_and_recovers(tmp_path, monkeypatch):
    data = b"complete retry bytes"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)

    class RecoverSession:
        trust_env = True

        def __init__(self):
            self.calls = []
            self.upload_bodies = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if url.endswith("b2_authorize_account"):
                return auth_response([{"id": "bucket-id", "name": "media"}])
            if url.endswith("b2_list_file_names"):
                return listing([])
            if url.endswith("b2_get_upload_url"):
                return Response(
                    {"uploadUrl": "https://upload.example", "authorizationToken": "t"}
                )
            if url == "https://upload.example":
                stream = kwargs["data"]
                if len(self.upload_bodies) == 0:
                    self.upload_bodies.append(stream.read(4))
                    raise requests.ConnectionError("partial synthetic failure")
                body = stream.read(5) + stream.read()
                self.upload_bodies.append(body)
                return uploaded_file("key", data)
            pytest.fail(f"unexpected synthetic request: {method} {url}")

    session = RecoverSession()
    events = []
    B2Client("id", "key", session=session).ensure_file(
        source, "media", "key", progress=lambda *event: events.append(event)
    )
    assert session.upload_bodies == [data[:4], data]
    assert sleep_calls == [30]
    assert ("retrying", 1, 5) in events
    assert [event[1] for event in events if event[0] == "uploading"] == [
        0,
        4,
        0,
        5,
        len(data),
    ]
    assert events[-1] == ("uploaded", len(data), len(data))


def test_lost_upload_response_is_verified_and_skipped_without_duplicate_post(
    tmp_path, monkeypatch
):
    data = b"maybe completed"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)

    class LostResponseSession:
        trust_env = True

        def __init__(self):
            self.calls = []
            self.uploads = 0
            self.completed = False

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if url.endswith("b2_authorize_account"):
                return auth_response([{"id": "bucket-id", "name": "media"}])
            if url.endswith("b2_list_file_names"):
                files = (
                    [
                        {
                            "fileName": "key",
                            "action": "upload",
                            "contentLength": len(data),
                            "contentSha1": hashlib.sha1(data).hexdigest(),
                        }
                    ]
                    if self.completed
                    else []
                )
                return listing(files)
            if url.endswith("b2_get_upload_url"):
                return Response(
                    {"uploadUrl": "https://upload.example", "authorizationToken": "t"}
                )
            if url == "https://upload.example":
                self.uploads += 1
                self.completed = True
                kwargs["data"].read()
                raise requests.ConnectionError("lost synthetic response")
            pytest.fail(f"unexpected synthetic request: {method} {url}")

    session = LostResponseSession()
    events = []
    B2Client("id", "key", session=session).ensure_file(
        source, "media", "key", progress=lambda *event: events.append(event)
    )
    assert session.uploads == 1
    assert sleep_calls == [30]
    assert events[-1] == ("skipped", len(data), len(data))
    assert "uploaded" not in [event[0] for event in events]


def test_multipart_retry_cancels_and_uses_fresh_upload_url(tmp_path, monkeypatch):
    data = b"abcdef"
    source = tmp_path / "large"
    source.write_bytes(data)
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "first-id"}),
            Response({"uploadUrl": "https://part-first", "authorizationToken": "t1"}),
            requests.ConnectionError("first part failed"),
            Response({}),
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "second-id"}),
            Response({"uploadUrl": "https://part-second", "authorizationToken": "t2"}),
            uploaded_part(b"abc", 1),
            uploaded_part(b"def", 2),
            uploaded_file("key", data, multipart=True),
        ]
    )

    B2Client("id", "key", session=session).ensure_file(source, "media", "key")

    cancels = [
        call for call in session.calls if call[1].endswith("b2_cancel_large_file")
    ]
    parts = [
        call
        for call in session.calls
        if call[2].get("headers", {}).get("X-Bz-Part-Number")
    ]
    assert len(cancels) == 1 and cancels[0][2]["json"] == {"fileId": "first-id"}
    assert [call[1] for call in parts] == [
        "https://part-first",
        "https://part-second",
        "https://part-second",
    ]
    assert sleep_calls == [30]


def test_retry_wait_interrupt_propagates_without_another_attempt(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"retry payload")
    monkeypatch.setattr(
        time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    class InterruptSession:
        trust_env = True

        def __init__(self):
            self.uploads = 0

        def request(self, method, url, **kwargs):
            if url.endswith("b2_authorize_account"):
                return auth_response([{"id": "bucket-id", "name": "media"}])
            if url.endswith("b2_list_file_names"):
                return listing([])
            if url.endswith("b2_get_upload_url"):
                return Response(
                    {"uploadUrl": "https://upload.example", "authorizationToken": "t"}
                )
            if url == "https://upload.example":
                self.uploads += 1
                raise requests.ConnectionError("synthetic failure")
            pytest.fail(f"unexpected synthetic request: {method} {url}")

    session = InterruptSession()
    with pytest.raises(KeyboardInterrupt):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert session.uploads == 1


def test_identical_object_reports_skip_without_upload(tmp_path):
    data = b"same"
    source = tmp_path / "source"
    source.write_bytes(data)
    events = []
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing(
                [
                    {
                        "fileName": "key",
                        "action": "upload",
                        "contentLength": len(data),
                        "contentSha1": hashlib.sha1(data).hexdigest(),
                    }
                ]
            ),
        ]
    )
    B2Client("id", "key", session=session).ensure_file(
        source, "media", "key", progress=lambda *event: events.append(event)
    )
    assert [event[0] for event in events][-1] == "skipped"
    assert "uploading" not in [event[0] for event in events]


def test_failed_single_confirmation_never_reports_verified_upload(
    tmp_path, monkeypatch
):
    disable_retries(monkeypatch)
    data = b"same"
    source = tmp_path / "source"
    source.write_bytes(data)
    events = []
    responses = single_upload_responses(data, "key")
    responses[-1] = uploaded_file("wrong-key", data)
    with pytest.raises(B2Error):
        B2Client("id", "key", session=FakeSession(responses)).ensure_file(
            source, "media", "key", progress=lambda *event: events.append(event)
        )
    assert "uploaded" not in [event[0] for event in events]


def test_invalid_upload_confirmation_exhausts_retries_without_verified_event(
    tmp_path, monkeypatch
):
    data = b"confirmation mismatch"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    events = []

    class InvalidConfirmationSession:
        trust_env = True

        def __init__(self):
            self.uploads = 0

        def request(self, method, url, **kwargs):
            if url.endswith("b2_authorize_account"):
                return auth_response([{"id": "bucket-id", "name": "media"}])
            if url.endswith("b2_list_file_names"):
                return listing([])
            if url.endswith("b2_get_upload_url"):
                return Response(
                    {"uploadUrl": "https://upload.example", "authorizationToken": "t"}
                )
            if url == "https://upload.example":
                self.uploads += 1
                kwargs["data"].read()
                return uploaded_file("wrong-key", data)
            pytest.fail(f"unexpected synthetic request: {method} {url}")

    session = InvalidConfirmationSession()
    with pytest.raises(B2Error, match="metadata does not match"):
        B2Client("id", "key", session=session).ensure_file(
            source, "media", "key", progress=lambda *event: events.append(event)
        )

    assert session.uploads == 6
    assert sleep_calls == [30, 30, 30, 30, 30]
    assert "uploaded" not in [event[0] for event in events]


def test_zero_byte_upload_reports_zero_without_false_full_percentage(tmp_path):
    source = tmp_path / "empty"
    source.write_bytes(b"")
    events = []
    session = FakeSession(single_upload_responses(b"", "key"))
    B2Client("id", "key", session=session).ensure_file(
        source, "media", "key", progress=lambda *event: events.append(event)
    )
    assert events[0] == ("hashing", 0, 0)
    assert events[-1] == ("uploaded", 0, 0)


def test_multipart_upload_progress_advances_only_after_confirmed_parts(
    tmp_path, monkeypatch
):
    data = b"abcdef"
    source = tmp_path / "large"
    source.write_bytes(data)
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    events = []
    order = []
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "new-id"}),
            Response({"uploadUrl": "https://part", "authorizationToken": "part-token"}),
            uploaded_part(b"abc", 1),
            uploaded_part(b"def", 2),
            uploaded_file("key", data, multipart=True),
        ]
    )
    session.before_response = lambda method, url, kwargs: (
        order.append("part-response")
        if method == "POST" and url == "https://part"
        else None
    )

    def report(*event):
        events.append(event)
        order.append(event)

    B2Client("id", "key", session=session).ensure_file(
        source, "media", "key", progress=report
    )
    assert [event[1] for event in events if event[0] == "uploading"] == [0, 3, 6]
    assert order.index(("uploading", 0, len(data))) < order.index("part-response")
    assert events[-1] == ("uploaded", len(data), len(data))


def test_vtt_content_type_is_explicit_case_insensitively(tmp_path):
    data = b"WEBVTT\n"
    source = tmp_path / "captions.VTT"
    source.write_bytes(data)
    responses = single_upload_responses(data, "captions.VTT")
    responses[-1] = uploaded_file("captions.VTT", data)
    session = FakeSession(responses)
    B2Client("id", "key", session=session).ensure_file(source, "media", "captions.VTT")
    assert session.calls[-1][2]["headers"]["Content-Type"] == "text/vtt"


def test_identical_existing_object_with_native_metadata_is_skipped(tmp_path):
    data = b"same"
    source = tmp_path / "a"
    source.write_bytes(data)
    object_metadata = {
        "fileName": "key",
        "action": "upload",
        "contentLength": len(data),
        "contentSha1": hashlib.sha1(data).hexdigest(),
    }
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([object_metadata]),
        ]
    )
    assert (
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")
        is None
    )
    assert len(session.calls) == 2
    assert session.calls[1][2]["json"] == {
        "bucketId": "bucket-id",
        "prefix": "key",
        "startFileName": "key",
        "maxFileCount": 1,
    }


def test_similarly_prefixed_object_is_not_treated_as_exact_key(tmp_path):
    data = b"same"
    source = tmp_path / "a"
    source.write_bytes(data)
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([{"fileName": "key-similar", "action": "upload"}]),
            Response({"uploadUrl": "upload", "authorizationToken": "token"}),
            uploaded_file("key", data),
        ]
    )
    B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert session.calls[-1][1] == "upload"


@pytest.mark.parametrize(
    "metadata",
    [
        {"contentLength": 4, "contentSha1": "bad"},
        {"contentLength": 3, "contentSha1": hashlib.sha1(b"same").hexdigest()},
        {"contentLength": True, "contentSha1": hashlib.sha1(b"same").hexdigest()},
    ],
)
def test_conflicting_existing_object_fails_closed(tmp_path, monkeypatch, metadata):
    disable_retries(monkeypatch)
    source = tmp_path / "a"
    source.write_bytes(b"same")
    item = {"fileName": "key", "action": "upload", **metadata}
    session = FakeSession(
        [auth_response([{"id": "bucket-id", "name": "media"}]), listing([item])]
    )
    with pytest.raises(B2Error):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert not any(call[1] == "upload" for call in session.calls)


def test_valid_conflicting_object_is_rechecked_on_all_six_attempts(
    tmp_path, monkeypatch
):
    source_data = b"source"
    existing_data = b"different existing content"
    source = tmp_path / "source.bin"
    source.write_bytes(source_data)
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    responses = []
    for _ in range(6):
        responses.extend(
            [
                auth_response([{"id": "bucket-id", "name": "media"}]),
                listing(
                    [
                        {
                            "fileName": "key",
                            "action": "upload",
                            "contentLength": len(existing_data),
                            "contentSha1": hashlib.sha1(existing_data).hexdigest(),
                        }
                    ]
                ),
            ]
        )
    session = FakeSession(responses)

    with pytest.raises(B2Error, match="conflicting content"):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")

    assert sum(call[1].endswith("b2_list_file_names") for call in session.calls) == 6
    assert sleeps == [30, 30, 30, 30, 30]
    assert not any(
        call[1].endswith("b2_get_upload_url")
        or call[1].endswith("b2_start_large_file")
        or call[1] == "upload"
        for call in session.calls
    )


def test_large_existing_object_uses_file_info_sha1(tmp_path):
    data = b"same"
    source = tmp_path / "a"
    source.write_bytes(data)
    item = {
        "fileName": "key",
        "action": "upload",
        "contentLength": len(data),
        "contentSha1": "none",
        "fileInfo": {"large_file_sha1": hashlib.sha1(data).hexdigest()},
    }
    session = FakeSession(
        [auth_response([{"id": "bucket-id", "name": "media"}]), listing([item])]
    )
    B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert len(session.calls) == 2


def test_malformed_listing_fails_closed(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "a"
    source.write_bytes(b"same")
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            Response({"files": "invalid"}),
        ]
    )
    with pytest.raises(B2Error):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")


def test_api_error_is_redacted(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "a"
    source.write_bytes(b"same")
    response = Response({"message": "secret body"}, status=403)
    session = FakeSession([requests.HTTPError("credential-secret", response=response)])
    with pytest.raises(B2Error) as error:
        B2Client("credential-secret", "private-key", session=session).ensure_file(
            source, "media", "key"
        )
    assert "secret" not in str(error.value)
    assert "credential" not in str(error.value)


def test_http_failure_reports_operation_and_status_without_hostile_details():
    url = "https://upload.example/object?token=url-secret"
    response = Response({"message": "body-secret"}, status=403)
    session = FakeSession([requests.HTTPError("exception-secret", response=response)])
    client = B2Client("id", "key", session=session)

    with pytest.raises(B2Error) as error:
        client._call("POST", url, operation="upload part")

    message = str(error.value)
    assert "upload part" in message
    assert "403" in message
    assert all(
        secret not in message
        for secret in (
            "upload.example",
            "url-secret",
            "body-secret",
            "exception-secret",
        )
    )


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (requests.Timeout("exception-secret"), "timeout"),
        (requests.ConnectionError("exception-secret"), "connection error"),
        (ValueError("exception-secret"), "invalid JSON"),
        (RuntimeError("exception-secret"), "unexpected response"),
    ],
)
def test_transport_failures_report_fixed_category_without_exception_text(
    exception, category
):
    session = FakeSession([exception])
    client = B2Client("id", "key", session=session)

    with pytest.raises(B2Error) as error:
        client._call(
            "POST",
            "https://upload.example/path?token=url-secret",
            operation="upload part",
        )

    message = str(error.value)
    assert "upload part" in message and category in message
    assert all(
        secret not in message
        for secret in ("upload.example", "url-secret", "exception-secret")
    )


def test_multipart_part_failure_names_operation_not_upload_url(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "large"
    source.write_bytes(b"abcdef")
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    url = "https://opaque-upload.example/path?token=upload-secret"
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "new-id"}),
            Response({"uploadUrl": url, "authorizationToken": "part-token"}),
            requests.ConnectionError("body-secret"),
            Response({}),
        ]
    )

    with pytest.raises(B2Error) as error:
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")

    message = str(error.value)
    assert "upload part" in message and "connection error" in message
    assert "unfinished upload may remain" not in message
    assert all(
        secret not in message
        for secret in ("opaque-upload.example", "upload-secret", "body-secret")
    )


def test_multipart_cancel_failure_preserves_upload_diagnostic_and_warning(
    tmp_path, monkeypatch
):
    disable_retries(monkeypatch)
    source = tmp_path / "large"
    source.write_bytes(b"abcdef")
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "new-id"}),
            Response(
                {
                    "uploadUrl": "https://opaque-upload.example/path?token=upload-secret",
                    "authorizationToken": "part-token",
                }
            ),
            requests.ConnectionError("upload-body-secret"),
            requests.ConnectionError("cancel-body-secret"),
        ]
    )

    with pytest.raises(B2Error) as error:
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")

    message = str(error.value)
    assert "upload part" in message and "connection error" in message
    assert "unfinished upload may remain" in message
    assert all(
        secret not in message
        for secret in (
            "opaque-upload.example",
            "upload-secret",
            "upload-body-secret",
            "cancel-body-secret",
        )
    )


def test_redirect_response_is_rejected(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "a"
    source.write_bytes(b"same")
    session = FakeSession([Response({}, status=302)])
    with pytest.raises(B2Error, match="redirect"):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert session.calls[0][2]["allow_redirects"] is False


def test_restricted_key_cannot_access_other_bucket(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "a"
    source.write_bytes(b"same")
    session = FakeSession([auth_response([{"id": "allowed-id", "name": "allowed"}])])
    with pytest.raises(B2Error, match="not accessible"):
        B2Client("id", "key", session=session).ensure_file(source, "other", "key")
    assert len(session.calls) == 1


@pytest.mark.parametrize("allowed_buckets", [None, []])
def test_unrestricted_key_resolves_bucket_by_name(tmp_path, allowed_buckets):
    source = tmp_path / "a"
    source.write_bytes(b"same")
    session = FakeSession(
        [
            auth_response(allowed_buckets),
            Response({"buckets": [{"bucketName": "media", "bucketId": "bucket-id"}]}),
            listing([]),
            Response({"uploadUrl": "upload", "authorizationToken": "token"}),
            uploaded_file("key", b"same"),
        ]
    )
    B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert session.calls[1][1].endswith("b2_list_buckets")
    assert session.calls[1][2]["json"] == {
        "accountId": "account-id",
        "bucketName": "media",
    }


def test_multipart_order_hash_metadata_and_prior_attempt_cleanup(tmp_path, monkeypatch):
    data = b"abcdefgh"
    source = tmp_path / "large"
    source.write_bytes(data)
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    part_hashes = [hashlib.sha1(part).hexdigest() for part in (b"abc", b"def", b"gh")]
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            Response(
                {
                    "files": [
                        {"fileName": "key-similar", "fileId": "do-not-cancel"},
                        {"fileName": "key", "fileId": "prior-id"},
                    ],
                    "nextFileId": None,
                }
            ),
            Response({}),
            Response({"fileId": "new-id"}),
            Response({"uploadUrl": "https://part", "authorizationToken": "part-token"}),
            uploaded_part(b"abc", 1),
            uploaded_part(b"def", 2),
            uploaded_part(b"gh", 3),
            uploaded_file("key", data, multipart=True),
        ]
    )
    progress = []
    B2Client("id", "key", session=session).ensure_file(
        source, "media", "key", progress=lambda *event: progress.append(event)
    )
    assert session.calls[2][2]["json"] == {
        "bucketId": "bucket-id",
        "namePrefix": "key",
        "maxFileCount": 1000,
    }
    cancellations = [
        call for call in session.calls if call[1].endswith("b2_cancel_large_file")
    ]
    assert [call[2]["json"]["fileId"] for call in cancellations] == ["prior-id"]
    parts = [
        call
        for call in session.calls
        if call[2].get("headers", {}).get("X-Bz-Part-Number")
    ]
    assert [call[2]["data"] for call in parts] == [b"abc", b"def", b"gh"]
    assert [call[2]["headers"]["X-Bz-Content-Sha1"] for call in parts] == part_hashes
    start = next(
        call for call in session.calls if call[1].endswith("b2_start_large_file")
    )
    assert (
        start[2]["json"]["fileInfo"]["large_file_sha1"]
        == hashlib.sha1(data).hexdigest()
    )
    finish = next(
        call for call in session.calls if call[1].endswith("b2_finish_large_file")
    )
    assert finish[2]["json"]["partSha1Array"] == part_hashes
    part_progress = [event for event in progress if event[0] == "uploading"]
    assert [event[1] for event in part_progress] == [0, 3, 6, 8]
    assert progress[-1] == ("uploaded", len(data), len(data))


def test_failed_multipart_part_never_reports_verified_upload(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "large"
    source.write_bytes(b"abcdef")
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    bad_part = uploaded_part(b"abc", 1)
    bad_part.payload["contentSha1"] = "0" * 40
    events = []
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "new-id"}),
            Response({"uploadUrl": "https://part", "authorizationToken": "part-token"}),
            bad_part,
            Response({}),
        ]
    )
    with pytest.raises(B2Error, match="part confirmation"):
        B2Client("id", "key", session=session).ensure_file(
            source, "media", "key", progress=lambda *event: events.append(event)
        )
    assert "uploaded" not in [event[0] for event in events]
    assert not any(call[1].endswith("b2_finish_large_file") for call in session.calls)


def test_failed_multipart_finish_never_reports_verified_upload_and_cancels(
    tmp_path, monkeypatch
):
    disable_retries(monkeypatch)
    data = b"abcdef"
    source = tmp_path / "large"
    source.write_bytes(data)
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    events = []
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "new-id"}),
            Response({"uploadUrl": "https://part", "authorizationToken": "part-token"}),
            uploaded_part(b"abc", 1),
            uploaded_part(b"def", 2),
            requests.ConnectionError("finish unavailable"),
            Response({}),
        ]
    )
    with pytest.raises(B2Error, match="B2 API request failed"):
        B2Client("id", "key", session=session).ensure_file(
            source, "media", "key", progress=lambda *event: events.append(event)
        )
    assert "uploaded" not in [event[0] for event in events]
    assert session.calls[-1][1].endswith("b2_cancel_large_file")


def test_prior_unfinished_cleanup_failure_prevents_new_upload(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "large"
    source.write_bytes(b"large")
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            Response(
                {
                    "files": [{"fileName": "key", "fileId": "prior-id"}],
                    "nextFileId": None,
                }
            ),
            requests.ConnectionError("cleanup secret"),
        ]
    )
    with pytest.raises(B2Error, match="Unable to cancel prior"):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert not any(call[1].endswith("b2_start_large_file") for call in session.calls)


def test_multipart_integrity_checks_actual_bytes_before_finish(tmp_path, monkeypatch):
    disable_retries(monkeypatch)
    source = tmp_path / "large"
    source.write_bytes(b"abcdef")
    monkeypatch.setattr("migration_storage.MAX_SINGLE_UPLOAD_SIZE", 4)
    monkeypatch.setattr("migration_storage.LARGE_FILE_PART_SIZE", 3)
    session = FakeSession(
        [
            auth_response([{"id": "bucket-id", "name": "media"}]),
            listing([]),
            empty_unfinished(),
            Response({"fileId": "new-id"}),
            Response({"uploadUrl": "https://part", "authorizationToken": "part-token"}),
            uploaded_part(b"cha", 1),
            uploaded_part(b"nge", 2),
            uploaded_part(b"d", 3),
            Response({}),
        ]
    )

    def mutate_after_hash(method, url, kwargs):
        if url.endswith("b2_get_upload_part_url"):
            source.write_bytes(b"changed")

    session.before_response = mutate_after_hash
    with pytest.raises(B2Error, match="changed during multipart"):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert not any(call[1].endswith("b2_finish_large_file") for call in session.calls)
    assert session.calls[-1][1].endswith("b2_cancel_large_file")
