import pytest
import requests

import migration_client as cli
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


def candidate(pk=1, kind="tv", path="Show/Season 1", filename="Episode.mkv"):
    return {
        "source_pk": pk,
        "mediafile_pk": None if kind == "tv" else 7,
        "kind": kind,
        "path": path,
        "filename": filename,
        "snapshot": f"snapshot-{pk}",
    }


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
