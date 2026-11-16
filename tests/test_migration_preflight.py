import json
import sys
import types
from pathlib import Path

import pytest

import migrate_to_b2 as cli
from migration_client import Config, MigrationError, ViewerClient


def candidate(source_pk, path, *, kind="tv", filename="episode.mkv", mediafile_pk=None):
    return {
        "source_pk": source_pk,
        "mediafile_pk": mediafile_pk,
        "kind": kind,
        "path": path,
        "filename": filename,
        "snapshot": f"secret-snapshot-{source_pk}",
    }


def config_for(tmp_path):
    base = tmp_path / "media"
    base.mkdir()
    return Config(
        "https://viewer.example/mediaviewer",
        base,
        (base,),
        "private-user",
        "private-pass",
        "",
        "",
        "https://b2.example",
    )


class Session:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        return page


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def page(items, cursor=None):
    return Response({"version": 1, "candidates": items, "next_cursor": cursor})


def report(capsys):
    captured = capsys.readouterr()
    return json.loads(captured.out), captured.err


def test_preflight_reports_every_ambiguous_directory_and_only_safe_json(
    tmp_path, capsys, monkeypatch
):
    config = config_for(tmp_path)
    one = config.base_path / "Movie One"
    two = config.base_path / "Movie Two"
    one.mkdir()
    two.mkdir()
    (one / "alpha.mkv").touch()
    (one / "beta.mp4").touch()
    (two / "gamma.avi").touch()
    (two / "delta.webm").touch()
    api = Session(
        [
            page(
                [
                    candidate(
                        11, "Movie One", kind="movie", filename="", mediafile_pk=101
                    ),
                    candidate(
                        12, "Movie Two", kind="movie", filename="", mediafile_pk=102
                    ),
                ]
            )
        ]
    )
    monkeypatch.setattr(
        cli, "_hash_file", lambda *_args: pytest.fail("preflight must not hash files")
    )

    assert cli.preflight(config=config, session=api) == 1
    data, _ = report(capsys)
    assert data == {
        "version": 1,
        "checked_candidates": 2,
        "resolved_candidates": 0,
        "issues": [
            {
                "type": "ambiguous_movie",
                "source_pk": 11,
                "mediafile_pk": 101,
                "directory": str(one),
                "video_candidates": ["alpha.mkv", "beta.mp4"],
            },
            {
                "type": "ambiguous_movie",
                "source_pk": 12,
                "mediafile_pk": 102,
                "directory": str(two),
                "video_candidates": ["delta.webm", "gamma.avi"],
            },
        ],
    }
    assert "snapshot" not in json.dumps(data)
    assert "private-user" not in json.dumps(data)
    assert "private-pass" not in json.dumps(data)
    assert [call[0] for call in api.calls] == ["GET"]
    assert api.calls[0][1] == (
        "https://viewer.example/mediaviewer/api/migrations/file-candidates/"
    )
    assert not list(config.base_path.rglob("*.tmp"))


def test_preflight_continues_for_valid_duplicate_missing_and_unsafe_candidates(
    tmp_path, capsys
):
    config = config_for(tmp_path)
    (config.base_path / "Show").mkdir()
    (config.base_path / "Show" / "episode.mkv").write_bytes(b"synthetic")
    api = Session(
        [
            page(
                [
                    candidate(1, "Show"),
                    candidate(2, "Show"),
                    candidate(3, "Absent"),
                    candidate(4, "../outside"),
                ]
            )
        ]
    )

    assert cli.preflight(config=config, session=api) == 1
    data, _ = report(capsys)
    assert data["checked_candidates"] == 4
    assert data["resolved_candidates"] == 2
    assert [issue["type"] for issue in data["issues"]] == [
        "duplicate_video",
        "source_error",
        "source_error",
    ]
    duplicate = data["issues"][0]
    assert duplicate["video"] == str(config.base_path / "Show" / "episode.mkv")
    assert duplicate["sources"] == [
        {"source_pk": 1, "mediafile_pk": None},
        {"source_pk": 2, "mediafile_pk": None},
    ]
    assert [issue["source_pk"] for issue in data["issues"][1:]] == [3, 4]
    assert [issue["path"] for issue in data["issues"][1:]] == [
        "Absent",
        "../outside",
    ]
    assert [issue["filename"] for issue in data["issues"][1:]] == [
        "episode.mkv",
        "episode.mkv",
    ]
    assert b"synthetic" == (config.base_path / "Show" / "episode.mkv").read_bytes()


def test_preflight_paginates_all_inventory_pages(tmp_path, capsys):
    config = config_for(tmp_path)
    directory = config.base_path / "Show"
    directory.mkdir()
    (directory / "episode.mkv").touch()
    api = Session([page([candidate(1, "Show")], "next"), page([], None)])

    assert cli.preflight(config=config, session=api) == 0
    data, _ = report(capsys)
    assert data == {
        "version": 1,
        "checked_candidates": 1,
        "resolved_candidates": 1,
        "issues": [],
    }
    assert len(api.calls) == 2
    assert [call[1] for call in api.calls] == [
        "https://viewer.example/mediaviewer/api/migrations/file-candidates/",
        "https://viewer.example/mediaviewer/api/migrations/file-candidates/",
    ]
    assert api.calls[1][2]["params"]["cursor"] == "next"


def test_preflight_resolves_exact_encoded_pair_without_mutation(tmp_path, capsys):
    config = config_for(tmp_path)
    directory = config.base_path / "Synthetic Movie"
    directory.mkdir()
    original = directory / "synthetic.mkv"
    encoded = directory / f"{original.name}.ALFRED-ENCODED.mp4"
    original.write_bytes(b"preserved original")
    encoded.write_bytes(b"selected encoded")
    api = Session(
        [
            page(
                [
                    candidate(
                        32,
                        "Synthetic Movie",
                        kind="movie",
                        filename="",
                    )
                ]
            )
        ]
    )

    assert cli.preflight(config=config, session=api) == 0
    data, _ = report(capsys)
    assert data == {
        "version": 1,
        "checked_candidates": 1,
        "resolved_candidates": 1,
        "issues": [],
    }
    assert [(method, url) for method, url, _ in api.calls] == [
        (
            "GET",
            "https://viewer.example/mediaviewer/api/migrations/file-candidates/",
        )
    ]
    assert original.read_bytes() == b"preserved original"
    assert encoded.read_bytes() == b"selected encoded"


def test_preflight_config_does_not_require_b2_but_migration_still_does(
    tmp_path, monkeypatch
):
    base = tmp_path / "media"
    base.mkdir()
    monkeypatch.setenv("MW_BASE_PATH", str(base))
    monkeypatch.setenv("MW_MEDIA_DIRS", str(base))
    monkeypatch.setenv("WAITER_USERNAME", "user")
    monkeypatch.setenv("WAITER_PASSWORD", "pass")
    monkeypatch.delenv("MW_B2_APPLICATION_KEY_ID", raising=False)
    monkeypatch.delenv("MW_B2_APPLICATION_KEY", raising=False)

    assert Config.from_env(require_b2=False).b2_key == ""
    with pytest.raises(MigrationError, match="Required migration environment"):
        Config.from_env()


def test_preflight_api_failure_is_safe_and_does_not_print_json(tmp_path, capsys):
    config = config_for(tmp_path)
    api = Session([RuntimeError("secret response body and credential")])
    assert cli.preflight(config=config, session=api) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Preflight stopped:")
    assert "secret response body" not in captured.err
    assert "credential" not in captured.err
    assert "Traceback" not in captured.err


def test_main_preflight_without_b2_env_is_get_only_and_read_only(
    tmp_path, monkeypatch, capsys
):
    base = tmp_path / "media"
    directory = base / "Synthetic Show"
    directory.mkdir(parents=True)
    source = directory / "synthetic-episode.mkv"
    source.write_bytes(b"unchanged synthetic content")
    base_url = "https://viewer.example/mediaviewer"
    monkeypatch.setenv("MW_BASE_PATH", str(base))
    monkeypatch.setenv("MW_MEDIA_DIRS", str(base))
    monkeypatch.setenv("MW_MEDIAVIEWER_BASE_URL", base_url)
    monkeypatch.setenv("WAITER_USERNAME", "synthetic-user")
    monkeypatch.setenv("WAITER_PASSWORD", "synthetic-password")
    monkeypatch.delenv("MW_B2_APPLICATION_KEY_ID", raising=False)
    monkeypatch.delenv("MW_B2_APPLICATION_KEY", raising=False)
    api = Session(
        [page([candidate(31, "Synthetic Show", filename="synthetic-episode.mkv")])]
    )

    def fail(*_args, **_kwargs):
        pytest.fail("preflight attempted a forbidden operation")

    monkeypatch.setattr(
        cli,
        "ViewerClient",
        lambda url, username, password, *, session=None: ViewerClient(
            url, username, password, session=api
        ),
    )
    monkeypatch.setattr(cli, "_hash_file", fail)
    monkeypatch.setattr(cli, "_run", fail)
    monkeypatch.setattr(cli, "_migrate_video", fail)
    monkeypatch.setattr(Path, "unlink", fail)
    monkeypatch.setattr(Path, "write_bytes", fail)
    monkeypatch.setattr(Path, "write_text", fail)
    monkeypatch.setattr(Path, "touch", fail)
    original_open = Path.open

    def guarded_open(path, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            fail()
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    storage = types.ModuleType("migration_storage")
    storage.B2Client = fail
    monkeypatch.setitem(sys.modules, "migration_storage", storage)

    assert cli.main(["--preflight"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["issues"] == []
    assert [(method, url) for method, url, _ in api.calls] == [
        (
            "GET",
            f"{base_url}/api/migrations/file-candidates/",
        )
    ]
    assert source.read_bytes() == b"unchanged synthetic content"


def test_main_dispatches_preflight_and_preserves_count_mode(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "preflight", lambda: called.append("preflight") or 0)
    monkeypatch.setattr(cli, "run", lambda count: called.append(count) or 0)
    assert cli.main(["--preflight"]) == 0
    assert cli.main(["3"]) == 0
    assert called == ["preflight", 3]
    with pytest.raises(SystemExit) as error:
        cli.main(["3", "--preflight"])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        cli.main([])
    assert error.value.code == 2
