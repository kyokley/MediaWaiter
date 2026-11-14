import inspect
from pathlib import Path

import pytest
import requests

import migrate_to_b2 as cli
from migration_client import HTTP_TIMEOUT


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
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.trust_env = True

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
        return value


class FakeB2:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def ensure_file(self, path, bucket, key):
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


def test_help_without_environment_and_old_journal_option_is_rejected(capsys):
    with pytest.raises(SystemExit) as help_exit:
        cli.main(["--help"])
    assert help_exit.value.code == 0
    assert "--journal" not in capsys.readouterr().out
    with pytest.raises(SystemExit) as old_option:
        cli.main(["1", "--writers-paused", "--journal", "x"])
    assert old_option.value.code == 2
    assert "unrecognized arguments: --journal x" in capsys.readouterr().err
    assert "journal_path" not in inspect.signature(cli.run).parameters


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
    (directory / "Episode2.vtt").write_bytes(b"unrelated")
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    session = success_session(candidate())
    b2 = FakeB2()
    assert cli.run(1, config=cli.Config.from_env(), session=session, b2_client=b2) == 0
    assert [x[0] for x in b2.calls] == [
        b"video bytes",
        b"WEBVTT commentary",
        b"WEBVTT en",
    ]
    assert all(x[1] == "server-bucket" and x[2].startswith("opaque/") for x in b2.calls)
    assert b2.calls[0][2].endswith(".mkv")
    assert all(x[2].endswith(".vtt") for x in b2.calls[1:])
    assert video.read_bytes() == b"video bytes"
    assert [call[0] for call in session.calls][-1] == "DELETE"
    assert set(tmp_path.iterdir()) == before
    assert not list(tmp_path.glob(".migration-to-b2*"))


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
        def ensure_file(self, *_):
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
