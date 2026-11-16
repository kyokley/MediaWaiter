"""Small upload-only client for the native Backblaze B2 v4 API."""

import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import quote

import requests

B2_API_VERSION = "v4"
DEFAULT_API_URL = "https://api.backblazeb2.com"
MAX_SINGLE_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024
LARGE_FILE_PART_SIZE = 100 * 1024 * 1024
API_TIMEOUT = 30
UPLOAD_TIMEOUT = 3600
HASH_CHUNK_SIZE = 1024 * 1024


def _notify(callback, event, bytes_done, total_bytes):
    if callback is not None:
        callback(event, bytes_done, total_bytes)


class _ProgressStream:
    """Count bytes as the HTTP client reads, without changing the file stream."""

    def __init__(self, stream, callback, total):
        self._stream = stream
        self._callback = callback
        self._total = total
        self._high_water = 0

    def read(self, size=-1):
        data = self._stream.read(size)
        position = self._stream.tell()
        if position > self._high_water:
            self._high_water = position
            _notify(
                self._callback,
                "uploading",
                min(self._high_water, self._total),
                self._total,
            )
        return data

    def __getattr__(self, name):
        return getattr(self._stream, name)


class B2Error(Exception):
    """Safe, credential-free error from the B2 storage client."""


class B2Client:
    """Upload files using Backblaze's native B2 v4 API."""

    def __init__(
        self,
        application_key_id,
        application_key,
        api_url=DEFAULT_API_URL,
        *,
        session=None,
    ):
        self._application_key_id = application_key_id
        self._application_key = application_key
        self._api_url = api_url.rstrip("/")
        self._session = session or requests.Session()
        self._session.trust_env = False
        self._auth = None

    def ensure_file(self, local_path, bucket, key, *, progress=None):
        path = Path(local_path)
        _notify(progress, "hashing", 0, 0)
        try:
            size = path.stat().st_size
            sha1 = self._file_sha1(path)
        except OSError:
            raise B2Error("Unable to read local upload file") from None
        _notify(progress, "hashing", size, size)
        _notify(progress, "checking", 0, size)
        auth = self._authorize()
        bucket_id = self._bucket_id(auth, bucket)
        existing = self._find_file(auth, bucket_id, key)
        if existing is not None:
            existing_size, existing_sha1 = self._file_metadata(existing)
            if existing_size == size and existing_sha1 == sha1:
                _notify(progress, "skipped", size, size)
                return None
            raise B2Error("B2 object already exists with conflicting content")
        try:
            if size > MAX_SINGLE_UPLOAD_SIZE:
                self._cancel_prior_large_files(auth, bucket_id, key)
                self._upload_large(path, size, sha1, bucket_id, key, auth, progress)
            else:
                self._upload_single(path, size, sha1, bucket_id, key, auth, progress)
        except B2Error:
            raise
        except Exception:
            raise B2Error(
                "B2 upload failed; verify object state before retrying"
            ) from None
        return None

    def _authorize(self):
        if self._auth is not None:
            return self._auth
        data = self._call(
            "GET",
            f"{self._api_url}/b2api/{B2_API_VERSION}/b2_authorize_account",
            auth=(self._application_key_id, self._application_key),
            timeout=API_TIMEOUT,
        )
        try:
            storage = data["apiInfo"]["storageApi"]
            allowed = storage["allowed"]
            if not isinstance(allowed, dict):
                raise ValueError
            if "buckets" not in allowed:
                raise ValueError
            allowed_buckets = allowed.get("buckets")
            if allowed_buckets is not None and not isinstance(allowed_buckets, list):
                raise ValueError
            buckets = None if not allowed_buckets else {}
            for item in allowed_buckets or []:
                if not isinstance(item, dict):
                    raise ValueError
                name = item.get("name")
                bucket_id = item.get("id", item.get("bucketId"))
                if not isinstance(name, str) or not isinstance(bucket_id, str):
                    raise ValueError
                buckets[name] = bucket_id
            self._auth = {
                "token": data["authorizationToken"],
                "api_url": storage["apiUrl"],
                "account_id": data["accountId"],
                "buckets": buckets,
            }
            if not all(
                isinstance(self._auth[field], str)
                for field in ("token", "api_url", "account_id")
            ):
                raise ValueError
            return self._auth
        except (KeyError, TypeError, ValueError):
            self._auth = None
            raise B2Error("Malformed B2 authorization response") from None

    def _bucket_id(self, auth, bucket):
        if auth["buckets"] is None:
            response = self._call(
                "POST",
                f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_list_buckets",
                json={"accountId": auth["account_id"], "bucketName": bucket},
                headers={"Authorization": auth["token"]},
                timeout=API_TIMEOUT,
            )
            buckets = response.get("buckets")
            if not isinstance(buckets, list):
                raise B2Error("Malformed B2 bucket listing response")
            matches = []
            for item in buckets:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("bucketName"), str)
                    or not isinstance(item.get("bucketId"), str)
                ):
                    raise B2Error("Malformed B2 bucket listing response")
                if item["bucketName"] == bucket:
                    matches.append(item["bucketId"])
            if len(matches) > 1 or (matches and not isinstance(matches[0], str)):
                raise B2Error("Malformed B2 bucket listing response")
            bucket_id = matches[0] if matches else None
        else:
            bucket_id = auth["buckets"].get(bucket)
        if not bucket_id:
            raise B2Error("Bucket is not accessible with this application key")
        return bucket_id

    def _find_file(self, auth, bucket_id, key):
        data = self._call(
            "POST",
            f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_list_file_names",
            json={
                "bucketId": bucket_id,
                "prefix": key,
                "startFileName": key,
                "maxFileCount": 1,
            },
            headers={"Authorization": auth["token"]},
            timeout=API_TIMEOUT,
        )
        files = data.get("files")
        if not isinstance(files, list) or len(files) > 1:
            raise B2Error("Malformed B2 file listing response")
        if not files:
            return None
        item = files[0]
        if not isinstance(item, dict) or not isinstance(item.get("fileName"), str):
            raise B2Error("Malformed B2 file listing response")
        if item["fileName"] != key:
            return None
        if item.get("action") != "upload":
            if item.get("action") == "hide":
                return None
            raise B2Error("Malformed B2 object metadata")
        self._file_metadata(item)
        return item

    @staticmethod
    def _file_metadata(item):
        content_length = item.get("contentLength")
        file_info = item.get("fileInfo", {})
        if (
            isinstance(content_length, bool)
            or not isinstance(content_length, int)
            or content_length < 0
            or not isinstance(file_info, dict)
        ):
            raise B2Error("Malformed B2 object metadata")
        sha1 = file_info.get("large_file_sha1", item.get("contentSha1"))
        if not B2Client._valid_sha1(sha1):
            raise B2Error("Malformed B2 object metadata")
        return content_length, sha1

    @staticmethod
    def _valid_sha1(value):
        return (
            isinstance(value, str)
            and len(value) == 40
            and all(character in "0123456789abcdefABCDEF" for character in value)
        )

    def _cancel_prior_large_files(self, auth, bucket_id, key):
        start_file_id = None
        seen_file_ids = set()
        while True:
            payload = {"bucketId": bucket_id, "namePrefix": key, "maxFileCount": 1000}
            if start_file_id is not None:
                payload["startFileId"] = start_file_id
            data = self._call(
                "POST",
                f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_list_unfinished_large_files",
                json=payload,
                headers={"Authorization": auth["token"]},
                timeout=API_TIMEOUT,
            )
            files = data.get("files")
            next_file_id = data.get("nextFileId")
            if (
                not isinstance(files, list)
                or "nextFileId" not in data
                or (next_file_id is not None and not isinstance(next_file_id, str))
            ):
                raise B2Error("Malformed B2 unfinished-file listing")
            for item in files:
                if not isinstance(item, dict) or not isinstance(
                    item.get("fileName"), str
                ):
                    raise B2Error("Malformed B2 unfinished-file listing")
                if item["fileName"] == key:
                    file_id = item.get("fileId")
                    if not isinstance(file_id, str) or not file_id:
                        raise B2Error("Malformed B2 unfinished-file metadata")
                    try:
                        self._call(
                            "POST",
                            f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_cancel_large_file",
                            json={"fileId": file_id},
                            headers={"Authorization": auth["token"]},
                            timeout=API_TIMEOUT,
                        )
                    except Exception:
                        raise B2Error(
                            "Unable to cancel prior unfinished multipart upload"
                        ) from None
            if next_file_id is not None and (
                not next_file_id or next_file_id in seen_file_ids
            ):
                raise B2Error("Malformed B2 unfinished-file listing")
            if next_file_id is None:
                return
            seen_file_ids.add(next_file_id)
            start_file_id = next_file_id

    def _upload_single(self, path, size, sha1, bucket_id, key, auth, progress=None):
        data = self._call(
            "GET",
            f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_get_upload_url",
            params={"bucketId": bucket_id},
            headers={"Authorization": auth["token"]},
            timeout=API_TIMEOUT,
        )
        try:
            upload_url = data["uploadUrl"]
            token = data["authorizationToken"]
            if not isinstance(upload_url, str) or not isinstance(token, str):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise B2Error("Malformed B2 upload URL response") from None
        headers = {
            "Authorization": token,
            "X-Bz-File-Name": quote(key, safe="/"),
            "Content-Type": self._content_type(path),
            "Content-Length": str(size),
            "X-Bz-Content-Sha1": sha1,
        }
        _notify(progress, "uploading", 0, size)
        with path.open("rb") as stream:
            stream = _ProgressStream(stream, progress, size)
            result = self._call(
                "POST", upload_url, data=stream, headers=headers, timeout=UPLOAD_TIMEOUT
            )
        self._validate_uploaded_file(result, key, size, sha1, multipart=False)
        _notify(progress, "uploaded", size, size)

    def _upload_large(self, path, size, sha1, bucket_id, key, auth, progress=None):
        start = self._call(
            "POST",
            f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_start_large_file",
            json={
                "bucketId": bucket_id,
                "fileName": key,
                "contentType": self._content_type(path),
                "fileInfo": {"large_file_sha1": sha1},
            },
            headers={"Authorization": auth["token"]},
            timeout=API_TIMEOUT,
        )
        file_id = start.get("fileId") if isinstance(start, dict) else None
        if not isinstance(file_id, str) or not file_id:
            raise B2Error("Malformed B2 multipart start response")
        try:
            part_upload = self._call(
                "GET",
                f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_get_upload_part_url",
                params={"fileId": file_id},
                headers={"Authorization": auth["token"]},
                timeout=API_TIMEOUT,
            )
            upload_url = part_upload["uploadUrl"]
            upload_token = part_upload["authorizationToken"]
            if not isinstance(upload_url, str) or not isinstance(upload_token, str):
                raise ValueError
            part_hashes = []
            whole_file_sha1 = hashlib.sha1(usedforsecurity=False)
            bytes_sent = 0
            _notify(progress, "uploading", 0, size)
            with path.open("rb") as stream:
                part_number = 1
                while True:
                    part = stream.read(LARGE_FILE_PART_SIZE)
                    if not part:
                        break
                    part_sha1 = hashlib.sha1(part, usedforsecurity=False).hexdigest()
                    whole_file_sha1.update(part)
                    bytes_sent += len(part)
                    part_result = self._call(
                        "POST",
                        upload_url,
                        data=part,
                        headers={
                            "Authorization": upload_token,
                            "X-Bz-Part-Number": str(part_number),
                            "Content-Length": str(len(part)),
                            "X-Bz-Content-Sha1": part_sha1,
                        },
                        timeout=UPLOAD_TIMEOUT,
                    )
                    part_length = part_result.get("contentLength")
                    if (
                        isinstance(part_length, bool)
                        or not isinstance(part_length, int)
                        or part_length != len(part)
                        or isinstance(part_result.get("partNumber"), bool)
                        or not isinstance(part_result.get("partNumber"), int)
                        or part_result.get("partNumber") != part_number
                        or part_result.get("contentSha1") != part_sha1
                    ):
                        raise B2Error(
                            "B2 multipart part confirmation does not match data"
                        )
                    part_hashes.append(part_sha1)
                    _notify(progress, "uploading", bytes_sent, size)
                    part_number += 1
            if bytes_sent != size or whole_file_sha1.hexdigest() != sha1:
                raise B2Error("Local file changed during multipart upload")
            result = self._call(
                "POST",
                f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_finish_large_file",
                json={"fileId": file_id, "partSha1Array": part_hashes},
                headers={"Authorization": auth["token"]},
                timeout=API_TIMEOUT,
            )
        except Exception:
            try:
                self._call(
                    "POST",
                    f"{auth['api_url']}/b2api/{B2_API_VERSION}/b2_cancel_large_file",
                    json={"fileId": file_id},
                    headers={"Authorization": auth["token"]},
                    timeout=API_TIMEOUT,
                )
            except Exception:
                raise B2Error(
                    "Multipart upload failed; unfinished upload may remain"
                ) from None
            raise
        self._validate_uploaded_file(result, key, size, sha1, multipart=True)
        _notify(progress, "uploaded", size, size)

    def _call(self, method, url, **kwargs):
        try:
            kwargs.setdefault("verify", True)
            kwargs.setdefault("allow_redirects", False)
            response = self._session.request(method, url, **kwargs)
            if 300 <= response.status_code < 400:
                raise B2Error("B2 API request returned a redirect")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise B2Error("Malformed B2 API response")
            return data
        except B2Error:
            raise
        except Exception:
            raise B2Error("B2 API request failed") from None

    @staticmethod
    def _validate_uploaded_file(data, key, size, sha1, *, multipart):
        if not isinstance(data.get("fileName"), str) or data["fileName"] != key:
            raise B2Error("B2 upload response metadata does not match requested object")
        content_length = data.get("contentLength")
        if (
            isinstance(content_length, bool)
            or not isinstance(content_length, int)
            or content_length != size
        ):
            raise B2Error("B2 upload response metadata does not match requested object")
        if multipart:
            file_info = data.get("fileInfo")
            actual_sha1 = (
                file_info.get("large_file_sha1")
                if isinstance(file_info, dict)
                else None
            )
        else:
            actual_sha1 = data.get("contentSha1")
        if actual_sha1 != sha1:
            raise B2Error("B2 upload response metadata does not match requested object")

    @staticmethod
    def _content_type(path):
        if Path(path).suffix.lower() == ".vtt":
            return "text/vtt"
        return mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    @staticmethod
    def _file_sha1(path):
        digest = hashlib.sha1(usedforsecurity=False)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()
