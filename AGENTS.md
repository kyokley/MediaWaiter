# MediaWaiter

MediaWaiter is a Flask media file server with streaming capabilities. It serves movie and TV media using token data from MediaViewer, renders media pages, and supports video progress, subtitles, and watch parties.

## Architecture and file map

- `waiter.py`: Flask application, HTTP routes, token validation, media listing, and file streaming. B2 tokens may include `original_filename` for the playable filename; `filename` remains the logical progress-hash namespace. Treat B2 `download_link` and subtitle URLs as opaque redirect targets, whether their object keys use legacy or nested paths; do not infer layouts or rewrite signed URLs.
- `settings.py`: Environment-backed application configuration; imports `local_settings.py` when present to override settings.
- `utils.py`, `log.py`: Shared helpers and logging.
- `migrate_to_b2.py`: Standalone REST-only local-to-B2 migration CLI; uploads existing videos and adjacent matching WebVTT subtitles without transcoding or deleting sources. Each invocation processes a fresh bounded batch with no persistent client state.
- `migration_client.py`: Migration environment configuration, isolated MediaViewer HTTP client, and local video/subtitle safety checks.
- `migration_storage.py`: Standalone native B2 upload client; verifies existing object content before skipping uploads and supports multipart files.
- `templates/`: Flask HTML templates.
- `static/assets/`: Browser JavaScript, stylesheets, and static assets.
- `tests/`: Pytest tests and fixtures.
- `pyproject.toml`: Python dependencies, Ruff rules, and pytest discovery configuration.
- `Makefile`: Docker build, test, security scan, and formatting targets.
- `Dockerfile`: Container build targets.
- `.github/workflows/pr.yml`: Pull request validation jobs.

## Development and validation

- `make pytest`: Run pytest in the Docker development container.
- `make bandit`: Run Bandit security scanning in the Docker development container.
- `make tests`: Run both `pytest` and `bandit` targets.
- `devenv test`: Run the devenv checks used by pull request CI.
- `make autoformat`: Run `ruff format` against the repository. This command mutates source files; review its diff before keeping changes.
- Pull request CI runs `make pytest`, `make bandit`, and `devenv test`.

## Configuration and security

- `settings.py` reads configuration from environment variables, including `MW_*`, `WAITER_*`, and Jitsi JWT settings. Keep credentials and secrets out of source control and logs.
- `MW_SECRET_FILE` can select the secret-key file. Otherwise settings use the repository-root `secret.txt`, creating it if absent. Never commit or expose secret files or their contents.
- Media directory validation uses `MW_BASE_PATH` and `MW_MEDIA_DIRS`. `MW_IGNORE_MEDIA_DIR_CHECKS` disables that validation; do not enable it as a substitute for correct deployment configuration.
- `local_settings.py` overrides imported settings. Keep local values private and do not add credentials to tracked files.
- Requests use TLS certificate verification by default (`VERIFY_REQUESTS = True`) and have a configured timeout. Preserve these safeguards unless a change has a documented, reviewed need.
- The migration CLI reads environment configuration directly, without importing application settings or MediaViewer code. It uses `WAITER_USERNAME`/`WAITER_PASSWORD` for MediaViewer and separate `MW_B2_APPLICATION_KEY_ID`/`MW_B2_APPLICATION_KEY` credentials for B2; see `README.md` for deployment and recovery instructions.
- Migration requires externally paused ordinary writers and an explicit `--writers-paused` acknowledgement. Its server lock coordinates migrations only and is released on normal exit paths. There is no journal or crash-resume support; failed runs may leave unpublished B2 objects, and hard kills may leave server ownership held. Inspect publication and ownership before manual cleanup. Bucket and opaque upload prefix come from MediaViewer.

## Conventions

- Before version-control operations, check whether Jujutsu is available with `command -v jj`. Use `jj` when available; use `git` otherwise.
- Follow existing Python and Flask patterns. Ruff lint selects `E` and `F` rules and ignores `E501`; pytest discovers `test_*.py` and the configured test filename patterns.
- Add or update tests in `tests/` for behavior changes. Run relevant validation targets before reporting completion.
- Update `AGENTS.md` in the same change whenever repository structure, behavior, commands, configuration, workflow, or conventions change. Verify every reference and remove stale instructions.
