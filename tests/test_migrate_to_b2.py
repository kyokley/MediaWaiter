import inspect
import os
from pathlib import Path

import pytest
import requests

import migrate_to_b2 as cli
from migration_client import HTTP_TIMEOUT
from migration_storage import B2Client, B2Error


class Response:
    def __init__(self, payload, status=200, url=None):
        self.payload = payload
        self.status_code = status
        self.url = url or "http://viewer/api/migrations/"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class ViewerSession:
    def __init__(self, responses, callback=None):
        self.responses = iter(responses)
        self.calls = []
        self.trust_env = True
        self.callback = callback

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        if (
            url.endswith("/api/migrations/run/")
            and method == "POST"
            and value.payload == {"locked": True}
        ):
            value.payload = {
                "acquired": True,
                "run_id": kwargs["json"]["run_id"],
                "owner_id": 7,
            }
        if (
            url.endswith("/api/migrations/run/")
            and method == "DELETE"
            and value.payload == {}
        ):
            value.payload = {"released": True}
        if self.callback:
            self.callback(method, url, kwargs)
        return value


class FakeB2:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def ensure_file(self, path, bucket, key, *, progress=None):
        data = Path(path).read_bytes()
        self.calls.append((data, bucket, key))
        if self.callback:
            self.callback(path)


def candidate(pk=1, kind="tv", path="Show/Season 1", filename="Episode.mkv"):
    return {
        "source_pk": pk,
        "mediafile_pk": None if kind == "tv" else 7,
        "kind": kind,
        "path": path,
        "filename": filename,
        "snapshot": f"snapshot-{pk}",
    }


def setup_config(tmp_path, monkeypatch):
    base = tmp_path / "media"
    base.mkdir()
    monkeypatch.setenv("MW_BASE_PATH", str(base))
    monkeypatch.setenv("MW_MEDIA_DIRS", str(base))
    monkeypatch.setenv("MW_MEDIAVIEWER_BASE_URL", "https://viewer.example/mediaviewer")
    monkeypatch.setenv("WAITER_USERNAME", "user")
    monkeypatch.setenv("WAITER_PASSWORD", "pass")
    monkeypatch.setenv("MW_B2_APPLICATION_KEY_ID", "id")
    monkeypatch.setenv("MW_B2_APPLICATION_KEY", "key")
    return base


def lock_response():
    return Response({"locked": True})


def candidates_response(*items):
    return Response({"version": 1, "candidates": list(items), "next_cursor": None})


def prepared_response(target=9):
    return Response(
        {
            "prepared": "token",
            "target_pk": target,
            "bucket": "server-bucket",
            "b2_upload_prefix": "opaque/",
        }
    )


def published_response(mediafile=8, target=9):
    return Response(
        {"published": True, "mediafile_pk": mediafile, "media_path_pk": target}
    )


def success_session(candidate_item, mediafile=8, target=9):
    return ViewerSession(
        [
            lock_response(),
            candidates_response(candidate_item),
            prepared_response(target),
            published_response(mediafile, target),
            Response({}),
        ]
    )


def test_help_without_environment_and_old_options_are_rejected(capsys, monkeypatch):
    with pytest.raises(SystemExit) as help_exit:
        cli.main(["--help"])
    assert help_exit.value.code == 0
    help_output = capsys.readouterr().out
    assert "--journal" not in help_output
    assert "--writers-paused" not in help_output
    monkeypatch.setattr(cli, "run", lambda *_: pytest.fail("run must not be called"))
    with pytest.raises(SystemExit) as old_flag:
        cli.main(["1", "--writers-paused"])
    assert old_flag.value.code == 2
    assert "unrecognized arguments: --writers-paused" in capsys.readouterr().err
    with pytest.raises(SystemExit) as old_option:
        cli.main(["1", "--journal", "x"])
    assert old_option.value.code == 2
    assert "unrecognized arguments: --journal x" in capsys.readouterr().err
    assert "journal_path" not in inspect.signature(cli.run).parameters


def test_main_delegates_integer_count_and_returns_run_result(monkeypatch):
    calls = []

    def fake_run(maximum):
        calls.append(maximum)
        return 23

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["4"]) == 23
    assert calls == [4]


def test_viewer_client_auth_timeout_redirect_and_http_status_are_safe():
    session = ViewerSession([Response({}, status=302, url="https://evil.example/")])
    client = cli.ViewerClient("https://viewer.example/", "u", "p", session=session)
    with pytest.raises(cli.MigrationError, match="redirect"):
        client.request("GET", "api/migrations/")
    options = session.calls[0][2]
    assert options["auth"] == ("u", "p")
    assert options["timeout"] == HTTP_TIMEOUT
    assert options["verify"] is True
    assert options["allow_redirects"] is False
    assert session.trust_env is False
    failed = ViewerSession([Response({"message": "private"}, status=403)])
    with pytest.raises(cli.MigrationError, match="403") as error:
        cli.ViewerClient("https://viewer.example", "u", "p", session=failed).request(
            "GET", "api/"
        )
    assert "private" not in str(error.value)


def test_viewer_client_http_failure_reports_only_method_and_path():
    failed = ViewerSession([Response({"message": "response-secret"}, status=404)])
    client = cli.ViewerClient(
        "https://user:password@viewer.example/mediaviewer/?token=query-secret#fragment-secret",
        "auth-user",
        "auth-password",
        session=failed,
    )

    with pytest.raises(cli.MigrationError) as error:
        client.request(
            "GET",
            "api/migrations/file-candidates/",
            params={"cursor": "cursor-secret"},
        )

    message = str(error.value)
    assert "GET" in message
    assert "/mediaviewer/api/migrations/file-candidates/" in message
    assert "HTTP 404" in message
    for secret in (
        "user",
        "password",
        "auth-user",
        "auth-password",
        "viewer.example",
        "query-secret",
        "fragment-secret",
        "cursor-secret",
        "response-secret",
    ):
        assert secret not in message


def test_viewer_client_request_failure_reports_only_method_and_path():
    failed = ViewerSession([requests.ConnectionError("exception-secret")])
    client = cli.ViewerClient(
        "https://user:password@viewer.example/mediaviewer/?token=query-secret#fragment-secret",
        "auth-user",
        "auth-password",
        session=failed,
    )

    with pytest.raises(cli.MigrationError) as error:
        client.request("POST", "api/migrations/run/")

    message = str(error.value)
    assert "POST" in message
    assert "/mediaviewer/api/migrations/run/" in message
    for secret in (
        "user",
        "password",
        "auth-user",
        "auth-password",
        "viewer.example",
        "query-secret",
        "fragment-secret",
        "exception-secret",
    ):
        assert secret not in message


def test_success_processes_video_and_all_subtitles_without_disk_state(
    tmp_path, monkeypatch
):
    base = setup_config(tmp_path, monkeypatch)
    directory = base / "Show" / "Season 1"
    directory.mkdir(parents=True)
    video = directory / "Episode.mkv"
    video.write_bytes(b"video bytes")
    (directory / "Episode.en.vtt").write_bytes(b"WEBVTT en")
    (directory / "Episode.commentary.2.VTT").write_bytes(b"WEBVTT commentary")
    (directory / "Episode.empty.vtt").write_bytes(b"")
    (directory / "Episode2.vtt").write_bytes(b"unrelated")
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    b2 = FakeB2()

    def assert_all_uploads_before_publish(method, url, _kwargs):
        if method == "POST" and "publish-file" in url:
            assert len(b2.calls) == 4

    session = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate()),
            prepared_response(),
            published_response(),
            Response({}),
        ],
        callback=assert_all_uploads_before_publish,
    )
    assert cli.run(1, config=cli.Config.from_env(), session=session, b2_client=b2) == 0
    assert [x[0] for x in b2.calls] == [
        b"video bytes",
        b"WEBVTT commentary",
        b"",
        b"WEBVTT en",
    ]
    assert all(x[1] == "server-bucket" and x[2].startswith("opaque/") for x in b2.calls)
    assert b2.calls[0][2].endswith(".mkv")
    assert all(x[2].endswith(".vtt") for x in b2.calls[1:])
    assert not video.exists()
    assert not (directory / "Episode.en.vtt").exists()
    assert not (directory / "Episode.commentary.2.VTT").exists()
    assert not (directory / "Episode.empty.vtt").exists()
    assert (directory / "Episode2.vtt").read_bytes() == b"unrelated"
    assert [call[0] for call in session.calls][-1] == "DELETE"
    assert set(tmp_path.iterdir()) == before
    assert not list(tmp_path.glob(".migration-to-b2*"))


def test_progress_logs_escaped_basename_and_partial_summary(
    tmp_path, monkeypatch, capsys
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    filename = "Episode\nprivate-snapshot.mp4"
    video = show / filename
    video.write_bytes(b"video")
    item = candidate(path="Show", filename=filename)
    item["snapshot"] = "private-snapshot-token"
    api = ViewerSession(
        [lock_response(), candidates_response(item), prepared_response(), Response({})]
    )
    b2 = FakeB2(
        lambda _path: (_ for _ in ()).throw(cli.MigrationError("upload failed"))
    )

    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) == 1

    log = capsys.readouterr().err
    assert "Inventory page 1: 1 candidates (1 total)" in log
    assert "Video 1/1: MediaPath 1" in log
    assert "Episode\\nprivate-snapshot.mp4" in log
    assert "private-snapshot-token" not in log
    assert "Publication confirmed" not in log
    assert "Video 1/1 complete" not in log
    assert "Migration summary: 0/1 videos complete" in log
    assert api.calls[-1][0] == "DELETE"


def test_preflight_stdout_remains_exact_json_and_progress_stays_off_stderr(
    tmp_path, monkeypatch, capsys
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    (show / "Episode.mp4").write_bytes(b"video")
    api = ViewerSession(
        [candidates_response(candidate(path="Show", filename="Episode.mp4"))]
    )

    assert cli.preflight(config=cli.Config.from_env(require_b2=False), session=api) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        '{"version": 1, "checked_candidates": 1, "resolved_candidates": 1, '
        '"issues": []}\n'
    )
    assert captured.err == ""


def test_upload_progress_throttles_intermediate_updates(monkeypatch, capsys):
    clock = iter((0.0, 0.0, 1.0, 5.0, 6.0))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(clock))
    progress = cli._UploadProgress("synthetic video")

    progress("uploading", 0, 10)
    progress("uploading", 1, 10)
    progress("uploading", 2, 10)
    progress("uploading", 10, 10)

    output = capsys.readouterr().err.splitlines()
    assert len(output) == 3
    assert "0/10 bytes" in output[0]
    assert "2/10 bytes" in output[1]
    assert "10/10 bytes (100.0%)" in output[2]


def test_real_b2_retry_exhaustion_retains_source_and_stops_before_publish(
    tmp_path, monkeypatch, capsys
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Episode.mp4"
    subtitle = show / "Episode.en.vtt"
    next_video = show / "Next.mp4"
    video.write_bytes(b"video")
    subtitle.write_bytes(b"WEBVTT captions")
    next_video.write_bytes(b"next video")
    next_candidate = candidate(2, path="Show", filename="Next.mp4")
    api = ViewerSession(
        [
            lock_response(),
            candidates_response(
                candidate(path="Show", filename="Episode.mp4"), next_candidate
            ),
            prepared_response(),
            Response({}),
        ]
    )
    delays = []
    monkeypatch.setattr("migration_storage.time.sleep", delays.append)
    b2 = B2Client("private-id", "private-key", session=ViewerSession([]))
    attempts = []

    def fail_single_attempt(_path, _bucket, _key, *, progress=None):
        attempts.append(True)
        if progress:
            progress("uploading", 0, len(b"video"))
            progress("uploading", len(b"video"), len(b"video"))
        raise B2Error("synthetic B2 upload failure")

    monkeypatch.setattr(b2, "_ensure_file_once", fail_single_attempt)

    assert cli.run(2, config=cli.Config.from_env(), session=api, b2_client=b2) == 1

    log = capsys.readouterr().err
    assert len(attempts) == 6
    assert delays == [30, 30, 30, 30, 30]
    assert [call[0] for call in api.calls] == ["POST", "GET", "POST", "DELETE"]
    assert video.read_bytes() == b"video"
    assert subtitle.read_bytes() == b"WEBVTT captions"
    assert next_video.read_bytes() == b"next video"
    assert "publish-file" not in " ".join(call[1] for call in api.calls)
    assert not any("prepare-file" in call[1] for call in api.calls[3:])
    assert "retry 1/5" in log and "retry 5/5" in log
    assert log.count("uploading 0/5 bytes") == 6
    assert "B2 upload verified" not in log
    assert "synthetic B2 upload failure" in log
    assert "Migration summary: 0/2 videos complete" in log
    assert "private-id" not in log and "private-key" not in log


def test_current_migration_http_contract(tmp_path, monkeypatch, capsys):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Episode.mp4"
    video.write_bytes(b"video bytes")
    item = candidate(path="Show", filename="Episode.mp4")
    item["mediafile_pk"] = 7
    api = success_session(item, mediafile=7)

    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) == 0
    )
    progress = capsys.readouterr().err
    stages = [
        "Video 1/1:",
        "Hashing 'Episode.mp4'",
        "Preparing MediaPath 1",
        "Checking B2 object",
        "Verifying sources before publishing",
        "Publication confirmed",
        "Verifying published sources",
        "Removing published video",
        "Video 1/1 complete",
        "Migration run lock release confirmed",
        "Migration summary: 1/1 videos complete",
    ]
    assert [progress.index(stage) for stage in stages] == sorted(
        progress.index(stage) for stage in stages
    )

    assert [
        (method, url.removeprefix("https://viewer.example/mediaviewer/"))
        for method, url, _ in api.calls
    ] == [
        ("POST", "api/migrations/run/"),
        ("GET", "api/migrations/file-candidates/"),
        ("POST", "api/migrations/1/prepare-file/"),
        ("POST", "api/migrations/1/publish-file/"),
        ("DELETE", "api/migrations/run/"),
    ]
    prepare = api.calls[2][2]["json"]
    assert prepare["file"] == {
        "pk": 7,
        "filename": "Episode.mp4",
        "b2_uuid": prepare["file"]["b2_uuid"],
        "size": len(b"video bytes"),
        "sha1": "398b2bda59339ce8651780bd9013b8326c2b5176",
        "subtitles": [],
    }
    assert prepare["snapshot"] == "snapshot-1"
    assert set(prepare) == {"run_id", "snapshot", "file"}
    assert api.calls[3][2]["json"] == {
        "run_id": prepare["run_id"],
        "prepared": "token",
    }
    assert api.calls[4][2]["json"] == {"run_id": prepare["run_id"]}


@pytest.mark.parametrize("items", [[], [candidate()]])
def test_candidate_pages_without_next_cursor_fail_closed_and_release_lock(
    tmp_path, monkeypatch, capsys, items
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Episode.mp4"
    video.write_bytes(b"video bytes")
    legacy_page = {"version": 1, "candidates": items}
    api = ViewerSession([lock_response(), Response(legacy_page), Response({})])
    b2 = FakeB2()

    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0

    error = capsys.readouterr().err
    assert "Malformed candidate cursor" in error
    assert "next_cursor" in error
    assert "KeyError" not in error
    assert [call[0] for call in api.calls] == ["POST", "GET", "DELETE"]
    assert api.calls[-1][2]["json"] == {"run_id": api.calls[0][2]["json"]["run_id"]}
    assert b2.calls == []
    assert video.read_bytes() == b"video bytes"
    assert not any(
        "prepare-file" in call[1] or "publish-file" in call[1] for call in api.calls
    )


def test_each_invocation_uses_fresh_run_and_current_inventory(tmp_path, monkeypatch):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    (show / "one.mp4").write_bytes(b"one")
    first_api = success_session(candidate(path="Show", filename="one.mp4"), mediafile=2)
    assert (
        cli.run(1, config=cli.Config.from_env(), session=first_api, b2_client=FakeB2())
        == 0
    )
    (show / "two.mp4").write_bytes(b"two")
    second_api = success_session(
        candidate(2, path="Show", filename="two.mp4"), mediafile=3
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=second_api, b2_client=FakeB2())
        == 0
    )
    first_id = first_api.calls[0][2]["json"]["run_id"]
    second_id = second_api.calls[0][2]["json"]["run_id"]
    assert first_id != second_id
    assert first_api.calls[1][2]["params"]["limit"] == 100
    assert second_api.calls[1][2]["params"]["limit"] == 100


def test_movie_publish_keeps_existing_mediafile_pk(tmp_path, monkeypatch):
    base = setup_config(tmp_path, monkeypatch)
    movie = base / "Movie"
    movie.mkdir()
    (movie / "Film.mp4").write_bytes(b"movie")
    item = candidate(4, kind="movie", path="Movie", filename="Film.mp4")
    api = success_session(item, mediafile=7, target=11)
    b2 = FakeB2()
    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) == 0
    prepare = next(call for call in api.calls if "prepare-file" in call[1])
    assert prepare[2]["json"]["file"]["pk"] == 7
    assert prepare[2]["json"]["file"]["filename"] == "Film.mp4"
    assert not (movie / "Film.mp4").exists()


@pytest.mark.parametrize("extension", ["avi", "mkv", "mp4"])
def test_movie_auto_discovery_prefers_exact_encoded_pair(tmp_path, extension):
    root = tmp_path / "root"
    movie = root / "Synthetic Movie"
    movie.mkdir(parents=True)
    original = movie / f"synthetic.{extension}"
    encoded = movie / f"{original.name}.ALFRED-ENCODED.mp4"
    original.write_bytes(b"original")
    encoded.write_bytes(b"encoded")

    selected = cli.resolve_candidate(
        candidate(kind="movie", path="Synthetic Movie", filename=""),
        [root],
        root,
    )

    assert selected == encoded


def test_movie_explicit_filename_overrides_encoded_pair_preference(tmp_path):
    root = tmp_path / "root"
    movie = root / "Synthetic Movie"
    movie.mkdir(parents=True)
    original = movie / "synthetic.mkv"
    encoded = movie / f"{original.name}.ALFRED-ENCODED.mp4"
    original.touch()
    encoded.touch()

    selected = cli.resolve_candidate(
        candidate(kind="movie", path="Synthetic Movie", filename=original.name),
        [root],
        root,
    )

    assert selected == original


@pytest.mark.parametrize(
    "names",
    [
        ("synthetic.mkv", "unrelated.ALFRED-ENCODED.mp4"),
        (
            "synthetic.mkv",
            "synthetic.mkv.ALFRED-ENCODED.mp4",
            "extra.avi",
        ),
        (
            "synthetic.mkv.ALFRED-ENCODED.mp4",
            "synthetic.mkv.ALFRED-ENCODED.mp4.ALFRED-ENCODED.mp4",
        ),
    ],
)
def test_movie_auto_discovery_rejects_non_exact_encoded_pairs(tmp_path, names):
    root = tmp_path / "root"
    movie = root / "Synthetic Movie"
    movie.mkdir(parents=True)
    for name in names:
        (movie / name).touch()

    with pytest.raises(cli.AmbiguousMovieError) as error:
        cli.resolve_candidate(
            candidate(kind="movie", path="Synthetic Movie", filename=""),
            [root],
            root,
        )

    assert error.value.video_candidates == tuple(sorted(names))


@pytest.mark.parametrize(
    "symlink_name", ["synthetic.mkv", "synthetic.mkv.ALFRED-ENCODED.mp4"]
)
def test_movie_auto_discovery_rejects_symlink_in_encoded_pair(tmp_path, symlink_name):
    root = tmp_path / "root"
    movie = root / "Synthetic Movie"
    movie.mkdir(parents=True)
    original = movie / "synthetic.mkv"
    encoded = movie / f"{original.name}.ALFRED-ENCODED.mp4"
    other = movie / "elsewhere"
    other.touch()
    (
        movie / (encoded.name if symlink_name == original.name else original.name)
    ).write_bytes(b"regular pair member")
    (movie / symlink_name).symlink_to(other)

    with pytest.raises(cli.AmbiguousMovieError) as error:
        cli.resolve_candidate(
            candidate(kind="movie", path="Synthetic Movie", filename=""),
            [root],
            root,
        )
    assert error.value.video_candidates == tuple(sorted((original.name, encoded.name)))


def test_run_movie_encoded_pair_uploads_and_removes_only_encoded_sources(
    tmp_path, monkeypatch
):
    base = setup_config(tmp_path, monkeypatch)
    movie = base / "Synthetic Movie"
    movie.mkdir()
    original = movie / "synthetic.mkv"
    encoded = movie / f"{original.name}.ALFRED-ENCODED.mp4"
    original_subtitle = movie / f"{original.name}.vtt"
    encoded_subtitle = movie / f"{encoded.name}.vtt"
    original.write_bytes(b"preserved original video")
    encoded.write_bytes(b"selected encoded video")
    original_subtitle.write_bytes(b"preserved original subtitle")
    encoded_subtitle.write_bytes(b"selected encoded subtitle")
    item = candidate(71, kind="movie", path="Synthetic Movie", filename="")
    item["mediafile_pk"] = None
    api = success_session(item, mediafile=72, target=73)
    b2 = FakeB2()

    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) == 0

    prepare = next(call for call in api.calls if "prepare-file" in call[1])
    manifest = prepare[2]["json"]["file"]
    assert manifest["filename"] == encoded.name
    assert len(manifest["subtitles"]) == 1
    assert [call[0] for call in b2.calls] == [
        b"selected encoded video",
        b"selected encoded subtitle",
    ]
    assert not encoded.exists()
    assert not encoded_subtitle.exists()
    assert original.read_bytes() == b"preserved original video"
    assert original_subtitle.read_bytes() == b"preserved original subtitle"


def test_inventory_paginates_and_caps_limit_for_large_maximum():
    class Client:
        def __init__(self):
            self.calls = []

        def request(self, method, path, *, params):
            self.calls.append(params)
            if len(self.calls) == 1:
                return {
                    "version": 1,
                    "candidates": [candidate()],
                    "next_cursor": "next",
                }
            return {"version": 1, "candidates": [], "next_cursor": None}

    client = Client()
    assert len(cli._inventory(client, 1001)) == 1
    assert all(call["limit"] == 1000 for call in client.calls)
    assert client.calls[1]["cursor"] == "next"


def test_inventory_stops_after_first_full_page_reaches_maximum():
    items = [candidate(1), candidate(2), candidate(3)]

    class Client:
        def __init__(self):
            self.calls = []

        def request(self, method, path, *, params):
            self.calls.append(params)
            return {
                "version": 1,
                "candidates": items,
                "next_cursor": "unfetched",
            }

    client = Client()

    assert cli._inventory(client, 2) == items
    assert len(client.calls) == 1


def test_inventory_stops_at_maximum_after_later_full_page():
    first_page = [candidate(1)]
    second_page = [candidate(2), candidate(3)]

    class Client:
        def __init__(self):
            self.calls = []

        def request(self, method, path, *, params):
            self.calls.append(params)
            if len(self.calls) == 1:
                return {
                    "version": 1,
                    "candidates": first_page,
                    "next_cursor": "next",
                }
            return {
                "version": 1,
                "candidates": second_page,
                "next_cursor": "unfetched",
            }

    client = Client()

    assert cli._inventory(client, 2) == first_page + second_page
    assert len(client.calls) == 2
    assert client.calls[1]["cursor"] == "next"


def test_inventory_returns_exhausted_candidates_below_maximum():
    items = [candidate()]

    class Client:
        def __init__(self):
            self.calls = []

        def request(self, method, path, *, params):
            self.calls.append(params)
            if len(self.calls) == 1:
                return {
                    "version": 1,
                    "candidates": items,
                    "next_cursor": "next",
                }
            return {"version": 1, "candidates": [], "next_cursor": None}

    client = Client()

    assert cli._inventory(client, 2) == items
    assert len(client.calls) == 2


def test_preflight_collects_full_inventory_when_count_reaches_maximum(
    tmp_path, monkeypatch, capsys
):
    setup_config(tmp_path, monkeypatch)
    items = [candidate(index) for index in range(1, 1001)]
    client = ViewerSession(
        [
            Response({"version": 1, "candidates": items, "next_cursor": "next"}),
            Response({"version": 1, "candidates": [], "next_cursor": None}),
        ]
    )

    assert (
        cli.preflight(config=cli.Config.from_env(require_b2=False), session=client) == 1
    )

    assert len(client.calls) == 2
    assert '"checked_candidates": 1000' in capsys.readouterr().out


def test_sidecars_are_not_counted_toward_video_limit(tmp_path, monkeypatch):
    base = setup_config(tmp_path, monkeypatch)
    directory = base / "Show"
    directory.mkdir()
    (directory / "one.mp4").write_bytes(b"one")
    (directory / "one.en.vtt").write_bytes(b"WEBVTT")
    plan = cli._new_plan([candidate(path="Show", filename="one.mp4")], 1, [base], base)
    assert len(plan) == 1
    assert len(plan[0]["sidecars"]) == 1


def test_sidecar_ownership_is_same_directory_and_local_inventory(tmp_path):
    root = tmp_path / "root"
    one, two = root / "Show1", root / "Show2"
    one.mkdir(parents=True)
    two.mkdir()
    (one / "Episode.mkv").write_bytes(b"one")
    (one / "Episode.Special.mkv").write_bytes(b"special")
    (one / "Episode.Special.en.vtt").write_bytes(b"WEBVTT")
    (two / "Episode.mkv").write_bytes(b"two")
    (two / "Episode.en.vtt").write_bytes(b"WEBVTT")
    plan = cli._new_plan(
        [
            candidate(1, path="Show1", filename="Episode.mkv"),
            candidate(2, path="Show2", filename="Episode.mkv"),
        ],
        2,
        [root],
        root,
    )
    assert plan[0]["sidecars"] == []
    assert plan[1]["sidecars"] == [str(two / "Episode.en.vtt")]


def test_tied_sidecar_owner_fails_closed(tmp_path):
    root = tmp_path / "root"
    directory = root / "Show"
    directory.mkdir(parents=True)
    for name in ("Episode.mp4", "episode.mp4"):
        (directory / name).write_bytes(name.encode())
    (directory / "Episode.en.vtt").write_bytes(b"WEBVTT")
    with pytest.raises(cli.MigrationError, match="Ambiguous subtitle"):
        cli._new_plan(
            [
                candidate(1, path="Show", filename="Episode.mp4"),
                candidate(2, path="Show", filename="episode.mp4"),
            ],
            2,
            [root],
            root,
        )


def test_matching_subtitle_symlink_is_rejected_without_upload_or_delete(
    tmp_path, monkeypatch
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Episode.mp4"
    video.write_bytes(b"video")
    target = show / "Shared.vtt"
    target.write_bytes(b"shared captions")
    link = show / "Episode.en.vtt"
    link.symlink_to(target)
    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Episode.mp4")),
            Response({}),
        ]
    )
    b2 = FakeB2()
    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0
    assert b2.calls == []
    assert video.read_bytes() == b"video"
    assert link.is_symlink() and target.read_bytes() == b"shared captions"
    assert api.calls[-1][0] == "DELETE"


def test_missing_candidates_skip_and_movie_blank_filename_rules(tmp_path):
    root = tmp_path / "root"
    (root / "Present").mkdir(parents=True)
    (root / "Present" / "Episode.mp4").write_bytes(b"video")
    plan = cli._new_plan(
        [
            candidate(1, path="Missing", filename="none.mp4"),
            candidate(2, path="Present", filename="Episode.mp4"),
        ],
        1,
        [root],
        root,
    )
    assert plan[0]["candidate"]["source_pk"] == 2
    empty = root / "Empty"
    empty.mkdir()
    with pytest.raises(cli.MigrationError, match="missing"):
        cli.resolve_candidate(
            candidate(kind="movie", path="Empty", filename=""), [root], root
        )
    (empty / "one.mp4").write_bytes(b"1")
    (empty / "two.mp4").write_bytes(b"2")
    with pytest.raises(cli.MigrationError, match="Ambiguous"):
        cli.resolve_candidate(
            candidate(kind="movie", path="Empty", filename=""), [root], root
        )


def test_traversal_symlink_and_bad_filename_are_rejected(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(cli.MigrationError):
        cli.resolve_candidate(candidate(path="../outside", filename="x.mp4"), [root])
    with pytest.raises(cli.MigrationError):
        cli.resolve_candidate(candidate(path="link", filename="x.mp4"), [root])
    (root / "Show").mkdir()
    with pytest.raises(cli.MigrationError):
        cli.resolve_candidate(candidate(path="Show", filename="bad\\name.mp4"), [root])


def test_failure_after_lock_attempts_release_and_never_publishes(tmp_path, monkeypatch):
    setup_config(tmp_path, monkeypatch)
    api = ViewerSession(
        [
            lock_response(),
            requests.ConnectionError("private"),
            Response({}),
        ]
    )
    b2 = FakeB2()
    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0
    assert [call[0] for call in api.calls][-1] == "DELETE"
    assert not any("publish-file" in call[1] for call in api.calls)


def test_inventory_404_reports_request_and_releases_lock_without_side_effects(
    tmp_path, monkeypatch, capsys
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Episode.mp4"
    video.write_bytes(b"video")
    api = ViewerSession(
        [
            lock_response(),
            Response({"message": "private response"}, status=404),
            Response({}),
        ]
    )
    b2 = FakeB2()

    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0

    error = capsys.readouterr().err
    assert "GET" in error
    assert "/mediaviewer/api/migrations/file-candidates/" in error
    assert "HTTP 404" in error
    assert "private response" not in error
    assert [call[0] for call in api.calls] == ["POST", "GET", "DELETE"]
    assert b2.calls == []
    assert not any("publish-file" in call[1] for call in api.calls)
    assert video.read_bytes() == b"video"


def test_local_video_inventory_reports_safe_resolution_diagnostic(
    tmp_path, monkeypatch
):
    base = tmp_path / "media"
    base.mkdir()
    video = base / "Episode.mp4"
    video.write_bytes(b"video")
    private_path = str(base / "private-secret.mp4")

    def fail_resolve(path, strict=False):
        if path.name == video.name and strict:
            raise FileNotFoundError(private_path)
        return original_resolve(path, strict=strict)

    original_resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", fail_resolve)

    with pytest.raises(cli.MigrationError) as error:
        cli.local_video_inventory(video, [base])

    message = str(error.value)
    assert "Episode.mp4" in message
    assert "FileNotFoundError" in message
    assert private_path not in message


def test_inventory_resolution_failure_reports_context_and_releases_lock(
    tmp_path, monkeypatch, capsys
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Episode.mp4"
    video.write_bytes(b"preserved source")
    bad_name = "bad\nname.mp4"
    other_video = show / bad_name
    other_video.write_bytes(b"other source")
    original_resolve = Path.resolve

    def fail_bad_entry(path, strict=False):
        if path.name == bad_name and strict:
            raise PermissionError("private error path /secret/credentials")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_bad_entry)
    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Episode.mp4")),
            Response({}),
        ]
    )
    b2 = FakeB2()

    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0

    error = capsys.readouterr().err
    assert "Selected 0 of requested 1 videos" not in error
    assert "0/? videos complete; selection incomplete" in error
    assert "Migration run lock release confirmed" in error
    assert "MediaPath 1" in error
    assert "bad\\nname.mp4" in error
    assert "PermissionError" in error
    assert "private error path" not in error
    assert "/secret/credentials" not in error
    assert [call[0] for call in api.calls] == ["POST", "GET", "DELETE"]
    assert not any("prepare-file" in call[1] for call in api.calls)
    assert not any("publish-file" in call[1] for call in api.calls)
    assert b2.calls == []
    assert video.read_bytes() == b"preserved source"
    assert other_video.read_bytes() == b"other source"


@pytest.mark.parametrize(
    ("source_ids", "mediafile_ids", "paths", "kind", "filename"),
    [
        ((31, 31), (301, 302), ("Show", "Show"), "tv", "Episode.mp4"),
        ((41, 42), (401, 402), ("Show", None), "tv", "Episode.mp4"),
        ((51, 51), (None, None), ("Film", "Film"), "movie", "Film.mp4"),
    ],
)
def test_ambiguous_candidates_report_resolved_path_and_both_ids_without_side_effects(
    tmp_path, monkeypatch, capsys, source_ids, mediafile_ids, paths, kind, filename
):
    base = setup_config(tmp_path, monkeypatch)
    folder = base / paths[0]
    folder.mkdir()
    video = folder / filename
    video.write_bytes(b"preserved source")
    candidate_rows = []
    for index, (source_pk, mediafile_pk, path) in enumerate(
        zip(source_ids, mediafile_ids, paths, strict=True)
    ):
        item = candidate(
            source_pk, kind=kind, path=path or str(folder), filename=filename
        )
        item["mediafile_pk"] = mediafile_pk
        item["snapshot"] = f"private-snapshot-{index}"
        candidate_rows.append(item)
    api = ViewerSession(
        [lock_response(), candidates_response(*candidate_rows), Response({})]
    )
    b2 = FakeB2()

    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0

    error = capsys.readouterr().err
    canonical_path = str(video.resolve())
    assert "Ambiguous duplicate candidates refer to the same physical video" in error
    assert repr(canonical_path) in error
    assert f"MediaPath {source_ids[0]}" in error
    assert f"MediaFile {mediafile_ids[0]!r}" in error
    assert f"MediaPath {source_ids[1]}" in error
    assert f"MediaFile {mediafile_ids[1]!r}" in error
    assert "private-snapshot" not in error
    assert [call[0] for call in api.calls] == ["POST", "GET", "DELETE"]
    run_id = api.calls[0][2]["json"]["run_id"]
    assert api.calls[-1][2]["json"] == {"run_id": run_id}
    assert not any("prepare-file" in call[1] for call in api.calls)
    assert not any("publish-file" in call[1] for call in api.calls)
    assert b2.calls == []
    assert video.read_bytes() == b"preserved source"


def test_prepare_failure_releases_lock(tmp_path, monkeypatch):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    (show / "Ep.mp4").write_bytes(b"video")
    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Ep.mp4")),
            Response({"bad": True}),
            Response({}),
        ]
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    assert [call[0] for call in api.calls][-1] == "DELETE"
    assert not any("publish-file" in call[1] for call in api.calls)


def test_rejected_lock_is_never_released(tmp_path, monkeypatch):
    setup_config(tmp_path, monkeypatch)
    api = ViewerSession(
        [Response({"acquired": False, "run_id": "other", "owner_id": 7})]
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    assert [call[0] for call in api.calls] == ["POST"]


def test_explicit_conflict_does_not_release_another_run(tmp_path, monkeypatch):
    setup_config(tmp_path, monkeypatch)
    api = ViewerSession([Response({"message": "busy"}, status=409)])
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    assert [call[0] for call in api.calls] == ["POST"]


def test_uncertain_acquire_attempts_same_run_cleanup(tmp_path, monkeypatch, capsys):
    setup_config(tmp_path, monkeypatch)
    api = ViewerSession([requests.ConnectionError("private"), Response({})])
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    assert [call[0] for call in api.calls] == ["POST", "DELETE"]
    assert "inspect MediaViewer /run ownership" not in capsys.readouterr().err


def test_lock_cleanup_failure_is_reported_and_nonzero(tmp_path, monkeypatch, capsys):
    base = setup_config(tmp_path, monkeypatch)
    (base / "Show").mkdir()
    api = ViewerSession(
        [lock_response(), candidates_response(), Response({"released": False})]
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    err = capsys.readouterr().err
    assert "lock may remain" in err
    assert "/run" in err


@pytest.mark.parametrize("change", ["video", "sidecar"])
def test_source_mutation_prevents_publish_and_releases_lock(
    tmp_path, monkeypatch, change
):
    base = setup_config(tmp_path, monkeypatch)
    directory = base / "Show"
    directory.mkdir()
    video = directory / "Ep.mp4"
    video.write_bytes(b"video")
    if change == "sidecar":
        (directory / "Ep.en.vtt").write_bytes(b"WEBVTT")

    def mutate(_path):
        if change == "video":
            video.write_bytes(b"changed")
        else:
            (directory / "Ep.fr.vtt").write_bytes(b"WEBVTT")

    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Ep.mp4")),
            prepared_response(),
            Response({}),
        ]
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2(mutate))
        != 0
    )
    assert not any("publish-file" in call[1] for call in api.calls)
    assert api.calls[-1][0] == "DELETE"


def test_keyboard_interrupt_after_acquire_releases_lock(tmp_path, monkeypatch):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    (show / "Ep.mp4").write_bytes(b"video")

    class InterruptB2:
        def ensure_file(self, *_, progress=None):
            raise KeyboardInterrupt

    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Ep.mp4")),
            prepared_response(),
            Response({}),
        ]
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=InterruptB2())
        != 0
    )
    assert api.calls[-1][0] == "DELETE"


def test_prepare_rejects_boolean_target_id_and_releases(tmp_path, monkeypatch):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    (show / "Ep.mp4").write_bytes(b"video")
    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Ep.mp4")),
            Response(
                {
                    "prepared": "token",
                    "target_pk": True,
                    "bucket": "b",
                    "b2_upload_prefix": "p/",
                }
            ),
            Response({}),
        ]
    )
    b2 = FakeB2()
    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0
    assert b2.calls == []
    assert api.calls[-1][0] == "DELETE"


def test_three_video_batch_preserves_frozen_sidecar_ownership_and_cap(
    tmp_path, monkeypatch
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    special, base_video, leftover = (
        show / name for name in ("Episode.Special.mp4", "Episode.mp4", "Other.mp4")
    )
    special.write_bytes(b"special")
    base_video.write_bytes(b"base")
    base_subtitle = show / "Episode.en.vtt"
    base_subtitle.write_bytes(b"BASE WEBVTT")
    leftover.write_bytes(b"leftover")
    (show / "Other.en.vtt").write_bytes(b"unselected captions")
    subtitle = show / "Episode.Special.en.vtt"
    subtitle.write_bytes(b"WEBVTT")
    items = [
        candidate(1, path="Show", filename="Episode.Special.mp4"),
        candidate(2, path="Show", filename="Episode.mp4"),
        candidate(3, path="Show", filename="Other.mp4"),
    ]
    api = ViewerSession(
        [
            lock_response(),
            candidates_response(*items),
            prepared_response(10),
            published_response(8, 10),
            prepared_response(11),
            published_response(9, 11),
            Response({}),
        ]
    )
    second_video_upload_started = []

    def assert_first_files_deleted(path):
        if Path(path) == base_video:
            second_video_upload_started.append(True)
            assert not special.exists()
            assert not subtitle.exists()

    b2 = FakeB2(assert_first_files_deleted)
    assert cli.run(2, config=cli.Config.from_env(), session=api, b2_client=b2) == 0
    assert second_video_upload_started
    assert not special.exists() and not base_video.exists()
    assert leftover.read_bytes() == b"leftover"
    assert (show / "Other.en.vtt").read_bytes() == b"unselected captions"
    assert not subtitle.exists()
    assert not base_subtitle.exists()
    assert [call[0] for call in b2.calls if call[0] == b"WEBVTT"] == [b"WEBVTT"]


@pytest.mark.parametrize("failure", ["upload", "publish_lost"])
def test_previous_files_stay_deleted_when_later_video_fails(
    tmp_path, monkeypatch, failure
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    first_video = show / "First.mp4"
    first_subtitle = show / "First.en.vtt"
    second_video = show / "Second.mp4"
    second_subtitle = show / "Second.en.vtt"
    first_video.write_bytes(b"first video")
    first_subtitle.write_bytes(b"FIRST WEBVTT")
    second_video.write_bytes(b"second video")
    second_subtitle.write_bytes(b"SECOND WEBVTT")
    api_responses = [
        lock_response(),
        candidates_response(
            candidate(1, path="Show", filename="First.mp4"),
            candidate(2, path="Show", filename="Second.mp4"),
        ),
        prepared_response(10),
        published_response(8, 10),
        prepared_response(11),
    ]
    if failure == "publish_lost":
        api_responses.append(requests.ConnectionError("private"))
    api_responses.append(Response({}))
    api = ViewerSession(api_responses)
    second_video_upload_started = []

    def fail_or_check_second_video(path):
        if Path(path) == second_video:
            second_video_upload_started.append(True)
            if failure == "upload":
                raise cli.MigrationError("upload failed")

    b2 = FakeB2(fail_or_check_second_video)
    assert cli.run(2, config=cli.Config.from_env(), session=api, b2_client=b2) == 1
    assert second_video_upload_started
    assert not first_video.exists()
    assert not first_subtitle.exists()
    assert second_video.read_bytes() == b"second video"
    assert second_subtitle.read_bytes() == b"SECOND WEBVTT"
    assert sum("publish-file" in call[1] for call in api.calls) == (
        1 if failure == "upload" else 2
    )
    assert len(b2.calls) == (3 if failure == "upload" else 4)
    assert api.calls[-1][0] == "DELETE"


@pytest.mark.parametrize(
    "failure",
    [
        "prepare",
        "upload",
        "subtitle_upload",
        "publish_http",
        "publish_lost",
        "publish_malformed",
    ],
)
def test_unconfirmed_publish_never_deletes_video(tmp_path, monkeypatch, failure):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Ep.mp4"
    video.write_bytes(b"video")
    subtitle = show / "Ep.en.vtt"
    subtitle.write_bytes(b"WEBVTT")
    api_responses = [
        lock_response(),
        candidates_response(candidate(path="Show", filename="Ep.mp4")),
    ]
    b2 = FakeB2()
    if failure == "prepare":
        api_responses.extend([Response({}), Response({})])
    else:
        api_responses.append(prepared_response())
        if failure == "publish_http":
            api_responses.extend(
                [Response({"message": "private"}, status=503), Response({})]
            )
        elif failure == "publish_lost":
            api_responses.extend([requests.ConnectionError("private"), Response({})])
        elif failure == "publish_malformed":
            api_responses.extend(
                [
                    Response(
                        {"published": True, "mediafile_pk": 8, "media_path_pk": 999}
                    ),
                    Response({}),
                ]
            )
        elif failure == "upload":
            api_responses.append(Response({}))
            b2 = FakeB2(
                lambda _: (_ for _ in ()).throw(cli.MigrationError("upload failed"))
            )
        elif failure == "subtitle_upload":
            (show / "Ep.fr.vtt").write_bytes(b"WEBVTT fr")
            count = [0]

            def fail_second_subtitle(_):
                count[0] += 1
                if count[0] == 3:
                    raise cli.MigrationError("subtitle upload failed")

            b2 = FakeB2(fail_second_subtitle)
    api = ViewerSession(api_responses)
    assert cli.run(1, config=cli.Config.from_env(), session=api, b2_client=b2) != 0
    assert video.read_bytes() == b"video"
    assert subtitle.read_bytes() == b"WEBVTT"
    if failure == "subtitle_upload":
        assert (show / "Ep.fr.vtt").read_bytes() == b"WEBVTT fr"
    assert api.calls[-1][0] == "DELETE"


@pytest.mark.parametrize("replacement_type", ["identical", "symlink"])
def test_replaced_video_after_publish_is_not_deleted(
    tmp_path, monkeypatch, replacement_type
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Ep.mp4"
    video.write_bytes(b"video")
    original_inode = video.stat().st_ino

    def replace_after_publish(method, url, _kwargs):
        if method == "POST" and "publish-file" in url:
            replacement = show / "replacement"
            replacement.write_bytes(b"video")
            if replacement_type == "symlink":
                replacement.unlink()
                target = show / "replacement-target"
                target.write_bytes(b"video")
                replacement.symlink_to(target)
            os.replace(replacement, video)

    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Ep.mp4")),
            prepared_response(),
            published_response(),
            Response({}),
        ],
        callback=replace_after_publish,
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    if replacement_type == "symlink":
        assert video.is_symlink() and video.read_bytes() == b"video"
    else:
        assert video.read_bytes() == b"video"
        assert video.stat().st_ino != original_inode
    assert api.calls[-1][0] == "DELETE"


@pytest.mark.parametrize("replacement_type", ["identical", "symlink"])
def test_replaced_subtitle_after_publish_keeps_all_local_sources(
    tmp_path, monkeypatch, replacement_type
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Ep.mp4"
    subtitle = show / "Ep.en.vtt"
    video.write_bytes(b"video")
    subtitle.write_bytes(b"WEBVTT")

    def replace_after_publish(method, url, _kwargs):
        if method == "POST" and "publish-file" in url:
            replacement = show / "replacement-vtt"
            replacement.write_bytes(b"WEBVTT")
            if replacement_type == "symlink":
                replacement.unlink()
                target = show / "shared.vtt"
                target.write_bytes(b"WEBVTT")
                replacement.symlink_to(target)
            os.replace(replacement, subtitle)

    api = ViewerSession(
        [
            lock_response(),
            candidates_response(candidate(path="Show", filename="Ep.mp4")),
            prepared_response(),
            published_response(),
            Response({}),
        ],
        callback=replace_after_publish,
    )
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    assert video.read_bytes() == b"video"
    if replacement_type == "symlink":
        assert subtitle.is_symlink() and subtitle.read_bytes() == b"WEBVTT"
    else:
        assert subtitle.read_bytes() == b"WEBVTT"
    assert api.calls[-1][0] == "DELETE"


def test_video_replaced_during_final_hash_is_not_deleted(tmp_path, monkeypatch):
    video = tmp_path / "Ep.mp4"
    video.write_bytes(b"original")
    identity = cli._source_identity(video)
    original_hash = cli._hash_file
    fingerprint = dict(zip(("size", "sha1"), original_hash(video)))

    def replace_during_hash(path):
        result = original_hash(path)
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"replacement")
        os.replace(replacement, video)
        return result

    monkeypatch.setattr(cli, "_hash_file", replace_during_hash)
    with pytest.raises(cli.MigrationError, match="local video changed"):
        cli._unlink_published_file(video, "video", [tmp_path], identity, fingerprint)
    assert video.read_bytes() == b"replacement"


def test_subtitle_replaced_during_final_hash_is_not_deleted(tmp_path, monkeypatch):
    subtitle = tmp_path / "Ep.en.vtt"
    subtitle.write_bytes(b"WEBVTT")
    identity = cli._source_identity(subtitle)
    original_hash = cli._hash_file
    fingerprint = dict(zip(("size", "sha1"), original_hash(subtitle)))

    def replace_during_hash(path):
        result = original_hash(path)
        replacement = tmp_path / "replacement.vtt"
        replacement.write_bytes(b"WEBVTT")
        os.replace(replacement, subtitle)
        return result

    monkeypatch.setattr(cli, "_hash_file", replace_during_hash)
    with pytest.raises(cli.MigrationError, match="local subtitle changed"):
        cli._unlink_published_file(
            subtitle, "subtitle", [tmp_path], identity, fingerprint
        )
    assert subtitle.read_bytes() == b"WEBVTT"


def test_unlink_failure_is_actionable_and_releases_lock(tmp_path, monkeypatch, capsys):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Ep.mp4"
    video.write_bytes(b"video")
    original_unlink = Path.unlink

    def fail_video_unlink(path, *args, **kwargs):
        if path == video:
            raise OSError("private filesystem detail")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_video_unlink)
    api = success_session(candidate(path="Show", filename="Ep.mp4"))
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    assert video.exists()
    error = capsys.readouterr().err
    assert "published successfully" in error and "local video remains" in error
    assert "private filesystem detail" not in error
    assert api.calls[-1][0] == "DELETE"


def test_subtitle_unlink_failure_keeps_video_and_releases_lock(
    tmp_path, monkeypatch, capsys
):
    base = setup_config(tmp_path, monkeypatch)
    show = base / "Show"
    show.mkdir()
    video = show / "Ep.mp4"
    subtitle = show / "Ep.en.vtt"
    video.write_bytes(b"video")
    subtitle.write_bytes(b"WEBVTT")
    original_unlink = Path.unlink

    def fail_subtitle_unlink(path, *args, **kwargs):
        if path == subtitle:
            raise OSError("private filesystem detail")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_subtitle_unlink)
    api = success_session(candidate(path="Show", filename="Ep.mp4"))
    assert (
        cli.run(1, config=cli.Config.from_env(), session=api, b2_client=FakeB2()) != 0
    )
    assert video.exists() and subtitle.exists()
    error = capsys.readouterr().err
    assert "local subtitle remains" in error
    assert "private filesystem detail" not in error
    assert api.calls[-1][0] == "DELETE"
