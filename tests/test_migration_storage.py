import hashlib

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


def test_uploads_unchanged_bytes_and_escapes_unicode_key(tmp_path):
    data = b"unchanged\x00bytes"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    key = "folder/caf\u00e9/\u03b2.bin"
    session = FakeSession(single_upload_responses(data, key))
    client = B2Client("id", "key", session=session)
    client.ensure_file(source, "media", key)
    upload = session.calls[-1]
    assert upload[2]["uploaded_bytes"] == data
    assert upload[2]["headers"]["X-Bz-File-Name"] == "folder/caf%C3%A9/%CE%B2.bin"
    assert upload[2]["headers"]["X-Bz-Content-Sha1"] == hashlib.sha1(data).hexdigest()
    assert session.trust_env is False
    assert all(call[2]["allow_redirects"] is False for call in session.calls)


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
def test_conflicting_existing_object_fails_closed(tmp_path, metadata):
    source = tmp_path / "a"
    source.write_bytes(b"same")
    item = {"fileName": "key", "action": "upload", **metadata}
    session = FakeSession(
        [auth_response([{"id": "bucket-id", "name": "media"}]), listing([item])]
    )
    with pytest.raises(B2Error):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")


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


def test_malformed_listing_fails_closed(tmp_path):
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


def test_api_error_is_redacted(tmp_path):
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


def test_redirect_response_is_rejected(tmp_path):
    source = tmp_path / "a"
    source.write_bytes(b"same")
    session = FakeSession([Response({}, status=302)])
    with pytest.raises(B2Error, match="redirect"):
        B2Client("id", "key", session=session).ensure_file(source, "media", "key")
    assert session.calls[0][2]["allow_redirects"] is False


def test_restricted_key_cannot_access_other_bucket(tmp_path):
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
    B2Client("id", "key", session=session).ensure_file(source, "media", "key")
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


def test_prior_unfinished_cleanup_failure_prevents_new_upload(tmp_path, monkeypatch):
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
