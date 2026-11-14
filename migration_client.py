"""Configuration, authenticated Viewer client, and safe media-file helpers."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests

DEFAULT_VIEWER_URL = "http://mediaviewer:8000/mediaviewer"
DEFAULT_B2_URL = "https://api.backblazeb2.com"
HTTP_TIMEOUT = (10, 60)
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".m4v",
    ".wmv",
    ".webm",
    ".mpg",
    ".mpeg",
    ".ts",
    ".m2ts",
    ".mpe",
    ".mpv",
    ".m2v",
    ".mts",
    ".3gp",
    ".flv",
    ".ogv",
    ".vob",
    ".divx",
    ".f4v",
    ".mxf",
}
HASH_CHUNK = 1024 * 1024


class MigrationError(Exception):
    """Safe, user-facing migration failure."""


@dataclass(frozen=True)
class Config:
    base_url: str
    base_path: Path
    roots: tuple[Path, ...]
    username: str
    password: str
    b2_key_id: str
    b2_key: str
    b2_api_url: str

    @classmethod
    def from_env(cls):
        base_value = os.environ.get("MW_BASE_PATH")
        roots_value = os.environ.get("MW_MEDIA_DIRS")
        required = {
            "WAITER_USERNAME": os.environ.get("WAITER_USERNAME"),
            "WAITER_PASSWORD": os.environ.get("WAITER_PASSWORD"),
            "MW_B2_APPLICATION_KEY_ID": os.environ.get("MW_B2_APPLICATION_KEY_ID"),
            "MW_B2_APPLICATION_KEY": os.environ.get("MW_B2_APPLICATION_KEY"),
        }
        if (
            not base_value
            or not roots_value
            or any(not value for value in required.values())
        ):
            raise MigrationError("Required migration environment is missing")
        base = Path(base_value).expanduser().resolve()
        roots = []
        for item in roots_value.split(","):
            if not item.strip():
                continue
            raw = Path(item.strip()).expanduser()
            roots.append((raw if raw.is_absolute() else base / raw).resolve())
        if not roots:
            raise MigrationError("MW_MEDIA_DIRS must contain at least one media root")
        return cls(
            os.environ.get("MW_MEDIAVIEWER_BASE_URL", DEFAULT_VIEWER_URL).rstrip("/"),
            base,
            tuple(roots),
            required["WAITER_USERNAME"],
            required["WAITER_PASSWORD"],
            required["MW_B2_APPLICATION_KEY_ID"],
            required["MW_B2_APPLICATION_KEY"],
            os.environ.get("MW_B2_API_URL", DEFAULT_B2_URL).rstrip("/"),
        )


class ViewerClient:
    """Independent, credential-scoped HTTP client for MediaViewer."""

    def __init__(self, base_url, username, password, *, session=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.auth = (username, password)
        self.session = session or requests.Session()
        self.session.trust_env = False

    def request(self, method, path, *, json_body=None, params=None):
        url = urljoin(self.base_url, path.lstrip("/"))
        try:
            response = self.session.request(
                method,
                url,
                auth=self.auth,
                json=json_body,
                params=params,
                timeout=HTTP_TIMEOUT,
                verify=True,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise MigrationError(
                    "MediaViewer returned a redirect; credentials were not forwarded"
                )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise MigrationError("Malformed MediaViewer response")
            return data
        except MigrationError:
            raise
        except requests.HTTPError as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            suffix = f" (HTTP {status})" if isinstance(status, int) else ""
            raise MigrationError(f"MediaViewer request failed{suffix}") from None
        except Exception:
            raise MigrationError("MediaViewer request failed") from None


def _inside(path, roots):
    return any(path == root or root in path.parents for root in roots)


def _safe_path(path):
    if "\x00" in path:
        raise MigrationError("Candidate path is malformed")
    parts = Path(path).parts
    if ".." in parts:
        raise MigrationError("Candidate path contains traversal")


def resolve_candidate(candidate, roots, base_path=None):
    if not isinstance(candidate, dict):
        raise MigrationError("Malformed candidate")
    kind, path, filename = (
        candidate.get("kind"),
        candidate.get("path"),
        candidate.get("filename"),
    )
    if kind not in ("tv", "movie") or not isinstance(path, str) or not path:
        raise MigrationError("Malformed candidate")
    _safe_path(path)
    root_list = tuple(Path(root).resolve() for root in roots)
    candidate_path = Path(path)
    if not candidate_path.is_absolute():
        if base_path is None:
            common = root_list[0]
            candidate_path = common / candidate_path
        else:
            candidate_path = Path(base_path) / candidate_path
    try:
        resolved_dir = candidate_path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise MigrationError("Candidate directory is missing or inaccessible") from None
    if not _inside(resolved_dir, root_list) or not resolved_dir.is_dir():
        raise MigrationError("Candidate directory escapes configured media roots")
    if kind == "movie" and filename in (None, ""):
        try:
            options = sorted(
                item
                for item in resolved_dir.iterdir()
                if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
            )
        except OSError:
            raise MigrationError("Unable to inspect movie directory") from None
        if not options:
            raise MigrationError("Candidate video is missing")
        if len(options) != 1:
            raise MigrationError(
                "Ambiguous movie directory; expected exactly one supported video"
            )
        video = options[0]
        if video.is_symlink():
            raise MigrationError("Candidate video symlink is not supported")
    else:
        if (
            not isinstance(filename, str)
            or not filename
            or "\x00" in filename
            or "\\" in filename
            or Path(filename).name != filename
            or filename in (".", "..")
        ):
            raise MigrationError("Candidate filename is malformed")
        if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:
            raise MigrationError("Candidate is not a supported video")
        video = resolved_dir / filename
        if video.is_symlink():
            raise MigrationError("Candidate video symlink is not supported")
        try:
            resolved_video = video.resolve(strict=True)
        except (OSError, RuntimeError):
            raise MigrationError("Candidate video is missing") from None
        if (
            resolved_video.parent != resolved_dir
            or not _inside(resolved_video, root_list)
            or not resolved_video.is_file()
        ):
            raise MigrationError("Candidate video escapes configured media roots")
        video = resolved_video
    if video.is_symlink() or not _inside(video.resolve(), root_list):
        raise MigrationError("Candidate video escapes configured media roots")
    return video


def _sidecar_matches(video, sidecar):
    if sidecar.suffix.lower() != ".vtt":
        return 0
    names = (video.stem, video.name)
    side_name = sidecar.name.casefold()
    matches = []
    for name in names:
        prefix = name.casefold()
        if side_name.startswith(prefix):
            rest = side_name[len(prefix) :]
            if rest.startswith((".", "_", "-", " ")):
                matches.append(len(prefix))
    return max(matches, default=0)


def find_sidecars(video, roots, peers=None):
    try:
        vtts = [
            item for item in video.parent.iterdir() if item.suffix.lower() == ".vtt"
        ]
    except OSError:
        raise MigrationError("Unable to inspect subtitle sidecars") from None
    matching = []
    for sidecar in vtts:
        contenders = (
            [Path(peer) for peer in peers if Path(peer).parent == video.parent]
            if peers
            else [video]
        )
        matches = [
            (score, peer)
            for peer in contenders
            if (score := _sidecar_matches(peer, sidecar))
        ]
        if not matches:
            continue
        best = max(score for score, _ in matches)
        winners = {str(peer.resolve()) for score, peer in matches if score == best}
        if len(winners) != 1:
            raise MigrationError(
                "Ambiguous subtitle sidecar matches multiple videos equally"
            )
        if str(video.resolve()) not in winners:
            continue
        try:
            resolved = sidecar.resolve(strict=True)
        except (OSError, RuntimeError):
            raise MigrationError("Subtitle sidecar is missing or unsafe") from None
        if (
            resolved.parent != video.parent.resolve()
            or not _inside(resolved, roots)
            or not resolved.is_file()
        ):
            raise MigrationError("Subtitle sidecar escapes configured media roots")
        matching.append((score, resolved))
    return sorted({item for _, item in matching})


def local_video_inventory(video, roots):
    """Return every supported, safe video beside video, including unregistered files."""
    try:
        entries = sorted(video.parent.iterdir())
    except OSError:
        raise MigrationError("Unable to inspect video directory") from None
    inventory = []
    for entry in entries:
        if entry.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if entry.is_symlink():
            raise MigrationError("Video symlink is not supported")
        try:
            resolved = entry.resolve(strict=True)
        except (OSError, RuntimeError):
            raise MigrationError("Video inventory changed or is inaccessible") from None
        if (
            resolved.parent != video.parent
            or not _inside(resolved, roots)
            or not resolved.is_file()
        ):
            raise MigrationError("Video inventory escapes configured media roots")
        inventory.append(str(resolved))
    return inventory


def _hash_file(path):
    digest = hashlib.sha1(usedforsecurity=False)
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(HASH_CHUNK), b""):
                digest.update(chunk)
        return path.stat().st_size, digest.hexdigest()
    except OSError:
        raise MigrationError("Unable to read a planned source file") from None


def _validate_candidates(data):
    if (
        type(data.get("version")) is not int
        or data.get("version") != 1
        or not isinstance(data.get("candidates"), list)
    ):
        raise MigrationError("Malformed candidate page")
    if data.get("next_cursor") is not None and not isinstance(data["next_cursor"], str):
        raise MigrationError("Malformed candidate cursor")
    for item in data["candidates"]:
        if (
            not isinstance(item, dict)
            or type(item.get("source_pk")) is not int
            or item["source_pk"] <= 0
            or not isinstance(item.get("snapshot"), str)
            or not item["snapshot"]
            or "mediafile_pk" not in item
            or (
                item["mediafile_pk"] is not None
                and (type(item["mediafile_pk"]) is not int or item["mediafile_pk"] <= 0)
            )
        ):
            raise MigrationError("Malformed candidate")
