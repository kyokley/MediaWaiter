"""Migrate a bounded batch to B2, deleting each video's sources after publication.

Each video's uploads, publication, and verified local cleanup finish before the
next video starts. Failed or uncertain publication retains that video's sources.
"""

import argparse
import json
import stat
import sys
import time
import uuid
from pathlib import Path

from migration_client import (
    Config,
    AmbiguousMovieError,
    MigrationError,
    ViewerClient,
    _hash_file,
    _validate_candidates,
    find_sidecars,
    local_video_inventory,
    resolve_candidate,
)
from migration_storage import B2Error, UPLOAD_RETRY_DELAY_SECONDS

PROGRESS_INTERVAL = 5.0


def _log(message):
    print(message, file=sys.stderr, flush=True)


class _UploadProgress:
    def __init__(self, label):
        self.label = label
        self.started = time.monotonic()
        self.last_update = self.started
        self.last_done = None

    def __call__(self, event, done, total):
        now = time.monotonic()
        final = event in {"uploaded", "skipped"}
        if event == "uploading":
            if self.last_done is None:
                self.started = now
                self.last_update = now
                self.last_done = done
                self._write(event, done, total, now)
            elif done > self.last_done and (
                done >= total or now - self.last_update >= PROGRESS_INTERVAL
            ):
                self.last_done = done
                self._write(event, done, total, now)
            return
        if event == "hashing":
            if done == 0:
                self._write("hashing", done, total, now)
            elif total:
                self._write("hashed", done, total, now)
            return
        if event == "checking":
            return
        if event == "retrying":
            self.last_done = None
            _log(
                f"{self.label}: retry {done}/{total} after B2 failure; "
                f"waiting {UPLOAD_RETRY_DELAY_SECONDS}s"
            )
            return
        if final:
            self._write(event, done, total, now)

    def _write(self, event, done, total, now):
        percent = f"{done * 100 / total:.1f}%" if total else "0.0%"
        if event == "skipped":
            _log(
                f"{self.label}: Existing B2 object verified; upload skipped ({total} bytes)"
            )
        elif event == "uploaded":
            elapsed = max(now - self.started, 0.0)
            rate = done / (1024 * 1024 * elapsed) if elapsed else 0.0
            _log(
                f"{self.label}: B2 upload verified {done}/{total} bytes ({percent}); "
                f"{elapsed:.1f}s, {rate:.2f} MiB/s"
            )
        elif event == "uploading":
            elapsed = max(now - self.started, 0.0)
            rate = done / (1024 * 1024 * elapsed) if elapsed else 0.0
            _log(
                f"{self.label}: uploading {done}/{total} bytes ({percent}); "
                f"{elapsed:.1f}s, {rate:.2f} MiB/s"
            )
        else:
            _log(f"{self.label}: {event} {done}/{total} bytes ({percent})")
        self.last_update = now


def _inventory(client, maximum, *, report_progress=False):
    candidates, cursor, seen_cursors = [], None, set()
    page_number = 0
    while True:
        page = client.request(
            "GET",
            "api/migrations/file-candidates/",
            params={"limit": min(max(maximum, 100), 1000), "cursor": cursor},
        )
        _validate_candidates(page)
        page_number += 1
        candidates.extend(page["candidates"])
        if report_progress:
            _log(
                f"Inventory page {page_number}: {len(page['candidates'])} candidates "
                f"({len(candidates)} total)"
            )
        cursor = page["next_cursor"]
        if cursor is None:
            return candidates
        if cursor in seen_cursors:
            raise MigrationError("Candidate pagination cursor repeated")
        seen_cursors.add(cursor)


def preflight(*, config=None, session=None):
    """Print a read-only source-selection audit and return its process status."""
    try:
        config = config or Config.from_env(require_b2=False)
        client = ViewerClient(
            config.base_url, config.username, config.password, session=session
        )
        candidates = _inventory(client, 1000)
        indexed_issues, resolved, by_video = [], [], {}
        for index, candidate in enumerate(candidates):
            source = {
                "source_pk": candidate["source_pk"],
                "mediafile_pk": candidate["mediafile_pk"],
            }
            try:
                video = resolve_candidate(candidate, config.roots, config.base_path)
            except AmbiguousMovieError as error:
                indexed_issues.append(
                    (
                        index,
                        {
                            "type": "ambiguous_movie",
                            **source,
                            "directory": str(error.directory),
                            "video_candidates": list(error.video_candidates),
                        },
                    )
                )
            except MigrationError as error:
                indexed_issues.append(
                    (
                        index,
                        {
                            "type": "source_error",
                            **source,
                            "path": candidate.get("path")
                            if isinstance(candidate.get("path"), str)
                            else None,
                            "filename": candidate.get("filename")
                            if isinstance(candidate.get("filename"), str)
                            else None,
                            "error": str(error),
                        },
                    )
                )
            else:
                video_path = str(video)
                resolved.append((index, video_path))
                by_video.setdefault(video_path, []).append(source)

        reported_duplicates = set()
        for index, video in resolved:
            sources = by_video[video]
            if len(sources) > 1 and video not in reported_duplicates:
                reported_duplicates.add(video)
                indexed_issues.append(
                    (
                        index,
                        {"type": "duplicate_video", "video": video, "sources": sources},
                    )
                )
        indexed_issues.sort(key=lambda entry: entry[0])
        payload = {
            "version": 1,
            "checked_candidates": len(candidates),
            "resolved_candidates": len(resolved),
            "issues": [issue for _, issue in indexed_issues],
        }
        print(json.dumps(payload, ensure_ascii=True))
        return int(bool(payload["issues"]))
    except KeyboardInterrupt:
        print("Preflight stopped: interrupted", file=sys.stderr)
    except MigrationError as error:
        print(f"Preflight stopped: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"Preflight stopped: operation failed ({type(error).__name__})",
            file=sys.stderr,
        )
    return 1


def _new_plan(candidates, maximum, roots, base_path):
    resolved, physical, missing = [], {}, []
    for candidate in candidates:
        try:
            video = resolve_candidate(candidate, roots, base_path)
        except MigrationError as error:
            if "missing" in str(error).lower():
                missing.append(candidate["source_pk"])
                continue
            raise
        canonical_path = str(video)
        if canonical_path in physical:
            first = physical[canonical_path]
            raise MigrationError(
                "Ambiguous duplicate candidates refer to the same physical video: "
                f"path={canonical_path!r}; "
                f"first=(MediaPath {first['source_pk']}, "
                f"MediaFile {first['mediafile_pk']!r}); "
                f"second=(MediaPath {candidate['source_pk']}, "
                f"MediaFile {candidate['mediafile_pk']!r})"
            )
        physical[canonical_path] = candidate
        resolved.append((candidate, video))
    if missing:
        shown = ", ".join(str(pk) for pk in missing[:10])
        rest = f" and {len(missing) - 10} more" if len(missing) > 10 else ""
        print(
            f"Skipped {len(missing)} missing candidates: {shown}{rest}", file=sys.stderr
        )
    plan = []
    for candidate, video in resolved[:maximum]:
        try:
            peers = local_video_inventory(video, roots)
        except MigrationError as error:
            raise MigrationError(
                f"Video inventory failed for MediaPath {candidate['source_pk']}: {error}"
            ) from None
        sidecars = [str(path) for path in find_sidecars(video, roots, peers)]
        plan.append(
            {
                "candidate": candidate,
                "video": str(video),
                "sidecars": sidecars,
                "sidecar_peers": peers.copy(),
                "video_inventory": peers,
            }
        )
    if len(plan) < maximum:
        print(f"Selected {len(plan)} of requested {maximum} videos", file=sys.stderr)
    return plan


def _manifest(video_path, sidecar_paths, candidate):
    video_size, video_sha = _hash_file(Path(video_path))
    if video_size <= 0:
        raise MigrationError("Video source is empty")
    subtitles, subtitle_map = [], {}
    fingerprints = {str(video_path): {"size": video_size, "sha1": video_sha}}
    for source in sidecar_paths:
        size, sha1 = _hash_file(Path(source))
        remote_name = f"{uuid.uuid4()}.vtt"
        subtitles.append({"filename": remote_name, "size": size, "sha1": sha1})
        subtitle_map[source] = remote_name
        fingerprints[source] = {"size": size, "sha1": sha1}
    manifest = {
        "pk": candidate.get("mediafile_pk"),
        "filename": Path(video_path).name,
        "b2_uuid": str(uuid.uuid4()),
        "size": video_size,
        "sha1": video_sha,
        "subtitles": subtitles,
    }
    return manifest, subtitle_map, fingerprints


def _source_identity(path):
    try:
        result = Path(path).lstat()
    except OSError:
        raise MigrationError("Original source is missing or inaccessible") from None
    if not stat.S_ISREG(result.st_mode):
        raise MigrationError("Original source is no longer a regular file")
    return {
        "device": result.st_dev,
        "inode": result.st_ino,
        "size": result.st_size,
        "mtime_ns": result.st_mtime_ns,
        "mode": result.st_mode,
    }


def _sources_changed(item, roots, fingerprints, identities):
    try:
        video = Path(item["video"])
        peers = local_video_inventory(video, roots)
        if peers != item["video_inventory"]:
            return True
        sidecars = [
            str(path) for path in find_sidecars(video, roots, item["sidecar_peers"])
        ]
        if sidecars != item["sidecars"]:
            return True
        for path, expected in fingerprints.items():
            if _source_identity(path) != identities[path] or _hash_file(Path(path)) != (
                expected["size"],
                expected["sha1"],
            ):
                return True
        return False
    except MigrationError:
        return True


def _verify_original_file(path, roots, identity, fingerprint):
    source = Path(path)
    if _source_identity(source) != identity:
        raise MigrationError("Published source changed")
    try:
        resolved = source.resolve(strict=True)
    except (OSError, RuntimeError):
        raise MigrationError("Published source path changed") from None
    if resolved != source or not any(
        resolved == Path(root).resolve() or Path(root).resolve() in resolved.parents
        for root in roots
    ):
        raise MigrationError("Published source path is outside configured media roots")
    if _hash_file(source) != (fingerprint["size"], fingerprint["sha1"]):
        raise MigrationError("Published source content changed")
    if _source_identity(source) != identity:
        raise MigrationError("Published source changed during verification")


def _unlink_published_file(path, kind, roots, identity, fingerprint):
    source = Path(path)
    try:
        _verify_original_file(source, roots, identity, fingerprint)
        source.unlink()
    except MigrationError:
        raise MigrationError(
            f"MediaViewer published successfully, but local {kind} changed and was left in place; earlier local sources may already be removed"
        ) from None
    except OSError:
        raise MigrationError(
            f"MediaViewer published successfully, but local {kind} remains; remove it manually after verifying playback; earlier local files may already be removed"
        ) from None


def _validate_prepared(response):
    if (
        not isinstance(response.get("prepared"), str)
        or not response["prepared"]
        or type(response.get("target_pk")) is not int
        or response["target_pk"] <= 0
        or not isinstance(response.get("bucket"), str)
        or not response["bucket"]
        or not isinstance(response.get("b2_upload_prefix"), str)
        or not response["b2_upload_prefix"]
    ):
        raise MigrationError("Malformed prepare-file response")


def _migrate_video(item, roots, run_id, client, b2_client):
    candidate = item["candidate"]
    source_paths = [*item["sidecars"], item["video"]]
    for path in source_paths:
        _log(f"Verifying source before migration: {Path(path).name!r}")
    identities = {path: _source_identity(path) for path in source_paths}
    _log(
        f"Hashing {Path(item['video']).name!r} and {len(item['sidecars'])} subtitle(s)"
    )
    manifest, subtitle_map, fingerprints = _manifest(
        item["video"], item["sidecars"], candidate
    )
    _log(f"Verifying sources before prepare for MediaPath {candidate['source_pk']}")
    if _sources_changed(item, roots, fingerprints, identities):
        raise MigrationError("A source file changed before prepare")
    _log(f"Preparing MediaPath {candidate['source_pk']} for upload")
    prepared = client.request(
        "POST",
        f"api/migrations/{candidate['source_pk']}/prepare-file/",
        json_body={
            "run_id": run_id,
            "snapshot": candidate["snapshot"],
            "file": manifest,
        },
    )
    _validate_prepared(prepared)
    video_key = (
        prepared["b2_upload_prefix"]
        + manifest["b2_uuid"]
        + Path(manifest["filename"]).suffix
    )
    video_label = (
        f"MediaPath {candidate['source_pk']} video {Path(item['video']).name!r}"
    )
    _log(f"Checking B2 object for {video_label}")
    b2_client.ensure_file(
        item["video"],
        prepared["bucket"],
        video_key,
        progress=_UploadProgress(video_label),
    )
    for source, remote_name in subtitle_map.items():
        label = f"MediaPath {candidate['source_pk']} subtitle {Path(source).name!r}"
        _log(f"Checking B2 object for {label}")
        b2_client.ensure_file(
            source,
            prepared["bucket"],
            prepared["b2_upload_prefix"] + remote_name,
            progress=_UploadProgress(label),
        )
    _log(f"Verifying sources before publishing MediaPath {candidate['source_pk']}")
    if _sources_changed(item, roots, fingerprints, identities):
        raise MigrationError("A source file changed before publish")
    result = client.request(
        "POST",
        f"api/migrations/{candidate['source_pk']}/publish-file/",
        json_body={"run_id": run_id, "prepared": prepared["prepared"]},
    )
    if (
        result.get("published") is not True
        or type(result.get("mediafile_pk")) is not int
        or result["mediafile_pk"] <= 0
        or type(result.get("media_path_pk")) is not int
        or result["media_path_pk"] != prepared["target_pk"]
        or (
            candidate.get("mediafile_pk") is not None
            and result["mediafile_pk"] != candidate["mediafile_pk"]
        )
    ):
        raise MigrationError("Malformed publish-file response")
    _log(f"Publication confirmed for MediaPath {candidate['source_pk']}")
    # Verify every uploaded original before deleting any, then remove subtitles first.
    try:
        _log(f"Verifying published sources for MediaPath {candidate['source_pk']}")
        for path in source_paths:
            _verify_original_file(path, roots, identities[path], fingerprints[path])
    except MigrationError:
        raise MigrationError(
            "MediaViewer published successfully, but a local source changed; no local files were removed"
        ) from None
    for path in [*item["sidecars"], item["video"]]:
        kind = "subtitle" if path != item["video"] else "video"
        _log(f"Removing published {kind} {Path(path).name!r}")
        _unlink_published_file(path, kind, roots, identities[path], fingerprints[path])
    return item["video"]


def _release(client, run_id):
    response = client.request(
        "DELETE", "api/migrations/run/", json_body={"run_id": run_id}
    )
    if response.get("released") is not True:
        raise MigrationError("MediaViewer migration lock release was not confirmed")


def _best_effort_release(client, run_id):
    try:
        _release(client, run_id)
        return True
    except BaseException:
        return False


def _run(maximum, *, config=None, session=None, b2_client=None):
    if type(maximum) is not int or maximum <= 0:
        raise MigrationError("Maximum video count must be a positive integer")
    config = config or Config.from_env()
    client = ViewerClient(
        config.base_url, config.username, config.password, session=session
    )
    if b2_client is None:
        from migration_storage import B2Client

        b2_client = B2Client(config.b2_key_id, config.b2_key, api_url=config.b2_api_url)
    run_id = str(uuid.uuid4())
    try:
        lock = client.request(
            "POST",
            "api/migrations/run/",
            json_body={"run_id": run_id, "writers_paused": True},
        )
    except BaseException as error:
        if "HTTP 409" in str(error):
            raise
        if not _best_effort_release(client, run_id):
            print(
                "Warning: lock acquisition is uncertain; inspect MediaViewer /run ownership",
                file=sys.stderr,
            )
        raise
    if lock.get("acquired") is not True:
        raise MigrationError("MediaViewer migration lock was not acquired")
    if lock.get("run_id") != run_id:
        raise MigrationError("MediaViewer migration lock belongs to another run")
    if type(lock.get("owner_id")) is not int or lock["owner_id"] <= 0:
        if not _best_effort_release(client, run_id):
            print(
                "Warning: migration lock may remain; inspect MediaViewer /run ownership",
                file=sys.stderr,
            )
        raise MigrationError("MediaViewer migration lock owner was not confirmed")
    primary_error = None
    cleanup_error = None
    started = time.monotonic()
    completed = 0
    selected = None
    try:
        _log(f"Migration run acquired: {run_id}")
        plan = _new_plan(
            _inventory(client, maximum, report_progress=True),
            maximum,
            config.roots,
            config.base_path,
        )
        selected = len(plan)
        _log(f"Selected {selected} of requested {maximum} videos")
        for index, item in enumerate(plan):
            candidate = item["candidate"]
            _log(
                f"Video {index + 1}/{selected}: MediaPath {candidate['source_pk']}, "
                f"MediaFile {candidate.get('mediafile_pk')!r}, "
                f"{Path(item['video']).name!r}"
            )
            deleted = _migrate_video(item, config.roots, run_id, client, b2_client)
            completed += 1
            _log(f"Video {completed}/{selected} complete after publication and cleanup")
            deleted_path = Path(deleted)
            for remaining in plan[index + 1 :]:
                if (
                    Path(remaining["video"]).parent == deleted_path.parent
                    and deleted in remaining["video_inventory"]
                ):
                    remaining["video_inventory"].remove(deleted)
    except BaseException as error:
        primary_error = error
    finally:
        try:
            _release(client, run_id)
        except BaseException as error:
            print(
                "Warning: migration lock may remain; inspect MediaViewer /run ownership",
                file=sys.stderr,
            )
            cleanup_error = error
        else:
            _log("Migration run lock release confirmed")
    progress_summary = (
        f"{completed}/{selected} videos complete"
        if selected is not None
        else f"{completed}/? videos complete; selection incomplete"
    )
    _log(
        f"Migration summary: {progress_summary}; elapsed {time.monotonic() - started:.1f}s"
    )
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise MigrationError("MediaViewer migration lock release was not confirmed")
    return 0


def run(maximum, *, config=None, session=None, b2_client=None):
    try:
        return _run(maximum, config=config, session=session, b2_client=b2_client)
    except KeyboardInterrupt:
        print(
            "Migration stopped: interrupted; lock cleanup was attempted",
            file=sys.stderr,
        )
    except (MigrationError, B2Error) as error:
        print(f"Migration stopped: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"Migration stopped: operation failed ({type(error).__name__})",
            file=sys.stderr,
        )
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "max_videos", nargs="?", type=int, help="maximum number of videos to migrate"
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="report source-selection issues without changing files",
    )
    args = parser.parse_args(argv)
    if args.preflight and args.max_videos is not None:
        parser.error("--preflight cannot be combined with max_videos")
    if args.preflight:
        return preflight()
    if args.max_videos is None:
        parser.error("max_videos is required unless --preflight is used")
    return run(args.max_videos)


if __name__ == "__main__":
    raise SystemExit(main())
