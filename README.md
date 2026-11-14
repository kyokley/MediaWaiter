# MediaWaiter [![Build Status](https://travis-ci.org/kyokley/MediaWaiter.svg)](https://travis-ci.org/kyokley/MediaWaiter)
A simple media file server with streaming capabilities

## Migrate local media to B2

`migrate_to_b2.py` uploads existing TV episodes and movies without transcoding,
then updates their existing MediaViewer records through REST. Adjacent matching
`.vtt` subtitles are uploaded unchanged. Local videos and subtitles are never
deleted. The integer argument limits **videos**, not subtitle objects.

Deploy the matching MediaViewer file-migration API and run its database
migrations first. Configure `B2_BUCKET_NAME` and `B2_NAME_PREFIX` in MediaViewer;
the script consumes its returned bucket and opaque upload prefix unchanged.

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

Pause MediaConverter, scrubbing jobs, and other writers that change the affected
MediaViewer records or local files. The migration lock coordinates migration
clients only; it does **not** pause ordinary writers. Keep them paused during
failure investigation too.

From the MediaWaiter checkout, migrate at most ten videos:

```sh
python migrate_to_b2.py 10 --writers-paused
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
Missing local files are skipped; ambiguous video/subtitle matches and stale
records fail closed. Retained local files are not evidence of an incomplete
migration: MediaViewer's published records determine playback location.
