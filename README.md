# MediaWaiter [![Build Status](https://travis-ci.org/kyokley/MediaWaiter.svg)](https://travis-ci.org/kyokley/MediaWaiter)
A simple media file server with streaming capabilities

## Migrate local media to B2

`migrate_to_b2.py` uploads existing TV episodes and movies without transcoding,
then updates their existing MediaViewer records through REST. Adjacent matching
`.vtt` subtitles are uploaded unchanged. Each original local video and its
uploaded subtitle files are deleted only after every upload succeeds and
MediaViewer confirms publication. Unrelated subtitles and files belonging to
unselected videos remain. The integer argument limits **videos**, not subtitle
objects.

Deploy the matching MediaViewer file-migration API and run its database
migrations first. Configure `B2_BUCKET_NAME` and `B2_NAME_PREFIX` in MediaViewer;
the script consumes its returned bucket and opaque upload prefix unchanged.

Verify `python manage.py show_urls` in the deployed MediaViewer runtime lists
`file-candidates/`, `{source_pk}/prepare-file/`, and `{source_pk}/publish-file/`
under `/mediaviewer/api/migrations/`. The backend requires migration
`0075_mediapath_migration_source`. The older `candidates/` and `publish/` actions
use a different protocol; changing the client URLs to those actions is unsafe.

Set these environment variables in MediaWaiter's runtime:

- `MW_BASE_PATH`: local media base directory.
- `MW_MEDIA_DIRS`: comma-separated media directories beneath that base, or
  absolute media roots. API paths must resolve within these roots; the script
  does not guess matches from directory basenames.
- `MW_MEDIAVIEWER_BASE_URL`: MediaViewer base URL, including `/mediaviewer`
  when deployed there. Prefer HTTPS; Basic Auth over HTTP requires a trusted
  private network.
- `WAITER_USERNAME`, `WAITER_PASSWORD`: MediaViewer credentials for a staff
  account. The configured Waiter authentication backend is supported.
- `MW_B2_APPLICATION_KEY_ID`, `MW_B2_APPLICATION_KEY`: B2 credentials with
  permission to list and upload objects in the destination bucket. Multipart
  failure cleanup also requires permission to list/cancel unfinished uploads.
  Unrestricted keys need `listBuckets` to resolve the server-returned bucket
  name; bucket-scoped keys use their authorization response's bucket ID.
- `MW_B2_API_URL`: optional native B2 API base URL; defaults to Backblaze.

### Inspect sources without migrating

Run the read-only source preflight where the configured local media paths are
accessible:

```sh
python migrate_to_b2.py --preflight > preflight.json
```

Do not supply a video count with `--preflight`. It scans the full candidate
inventory using MediaViewer GET requests, without acquiring a migration lock,
initializing B2, uploading, publishing, hashing file contents, or deleting files.
Only the media-path configuration and MediaViewer credentials above are needed;
B2 credentials are not required.

The JSON report includes `version`, `checked_candidates`, `resolved_candidates`,
and `issues`. Ambiguous movies include their `source_pk` (MediaPath ID),
`mediafile_pk` (MediaFile ID, possibly null), directory, and supported video
filenames. Other unresolved sources and duplicate video references are reported
as well. Signed snapshots and credentials are omitted. Reports contain local
paths and filenames; keep them private.

Exit status is `0` when no issues are found, or `1` when issues or configuration/API
errors occur. Configuration/API errors go to stderr and may leave no JSON report.
Missing sources are reported as issues even though a normal migration skips them.
The report is a point-in-time source-selection audit, not an upload, subtitle,
storage-integrity, or playback check. Preflight uses the movie-selection rules
below without changing files or records. Review any remaining ambiguities and
set the intended filenames in MediaViewer.

### Movie file selection

An explicit movie filename takes precedence. When it is blank, a directory with
one supported video uses that file. A directory with exactly two supported video
files may use the legacy encoded copy instead: exactly one filename must end in
the case-sensitive suffix `.ALFRED-ENCODED.mp4`, and its complete name must equal
the other filename plus that suffix. Both files must be regular, nonsymlink
files. Unrelated names, additional videos, multiple encoded files, and
double-encoded chains remain ambiguous.

For an accepted pair, migration uploads the encoded video and its matching
subtitles. After confirmed publication, cleanup removes only those uploaded
sources. The original video and its own matching subtitles remain untouched.
Preflight reports other ambiguous arrangements; normal migration stops on them.

### Run the migration

Pause MediaConverter, scrubbing jobs, and other writers that change the affected
MediaViewer records or local files. The migration lock coordinates migration
clients only; it does **not** pause ordinary writers. Keep them paused during
failure investigation too.

From the MediaWaiter checkout, migrate at most ten videos:

```sh
python migrate_to_b2.py 10
```

Each invocation selects a fresh batch and keeps its state only in memory. There
is no journal or crash-resume support. Already published records are excluded
from later batches, but interrupted uploads can leave unpublished B2 objects.
Rerunning creates new object UUIDs and may require manual orphan cleanup; do not
delete objects without first checking whether MediaViewer published them.

The script attempts to release its server lock on success, failure, and normal
interruption. A hard kill or network failure may leave the lock held. Inspect
`GET /api/migrations/run/` and confirm no migration is running before releasing
it with `DELETE /api/migrations/run/`, using the returned `run_id` and the same
authenticated account. The script prints its run ID after acquiring ownership.

Each TV episode keeps its record ID and moves to a reserved B2 MediaPath only
after all its uploads succeed. Unselected episodes retain their local path.
Movies retain their existing MediaPath, which changes to B2 only at publication.
Missing local files are skipped; ambiguous video/subtitle matches, symlinked
sources, and stale records fail closed. Failed or uncertain publication retains
the original video and subtitles. Cleanup checks that all uploaded sources
remain unchanged, then removes matching subtitles before the video. A changed
source or deletion error
can leave local originals even when MediaViewer already published them; an OS
deletion error may leave partially completed local cleanup. Verify the published
record before manual removal. A later run does not automatically clean up files
whose records are already in B2.

If planning reports duplicate candidates for the same video, the error shows the
resolved local path and both conflicting MediaPath/MediaFile ID pairs. A `None`
MediaFile ID means the movie does not yet have a child record. This safety check
covers the entire inventory, even with a limit of one video, and stops before
uploads or local deletion. Inspect the named records and their path mappings;
do not remove the guard or choose one record arbitrarily, since deleting a shared
source could break playback for the other record.
