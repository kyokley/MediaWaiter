import time
import requests
import logging

from .settings import (
    APP_NAME,
    MEDIAVIEWER_BASE_URL,
    MEDIAVIEWER_GUID_OFFSET_URL,
    WAITER_USERNAME,
    WAITER_PASSWORD,
    VERIFY_REQUESTS,
    SECRET_KEY,
    MEDIAWAITER_PROTOCOL,
    HOST,
    PORT,
    REQUESTS_TIMEOUT,
)
import hashlib

logger = logging.getLogger(__file__)

ONE_MB = 1000000

suffixes = ["B", "KB", "MB", "GB", "TB", "PB"]


def humansize(nbytes):
    if nbytes == 0:
        return "0 B"
    i = 0
    while nbytes >= 1024 and i < len(suffixes) - 1:
        nbytes /= 1024.0
        i += 1
    val = ("%.2f" % nbytes).rstrip("0").rstrip(".")
    return f"{val} {suffixes[i]}"


class delayedRetry:
    def __init__(self, attempts=5, interval=1):
        self.attempts = attempts
        self.interval = interval

    def __call__(self, func):
        def wrap(*args, **kwargs):
            logger().debug(f"Attempting {func.__name__}")
            last_exc = None
            for i in range(self.attempts):
                try:
                    logger().debug(f"Attempt {i}")
                    res = func(*args, **kwargs)
                    logger().debug("Success")
                    return res
                except Exception as e:
                    logger().error(e)
                    last_exc = e
                time.sleep(self.interval)
            else:
                logger().error(f"Failure after {self.attempts} attempts")
                raise last_exc

        return wrap


def checkForValidToken(token, guid):
    if not token:
        logger().warn(f"Token is invalid GUID: {guid}")
        return "This token is invalid! Return to Movie or TV Show tab to generate a new one."
    if not token["isvalid"]:
        logger().warn(f"Token Expired GUID: {guid}")
        return "This token has expired! Return to Movie or TV Show tab to generate a new one."


def buildWaiterPath(place, guid, filePath, includeLastSlash=True):
    path = "{protocol}{host}:{port}{app_name}/{place}/{guid}{maybe_slash}{file_path}".format(
        protocol=MEDIAWAITER_PROTOCOL,
        host=HOST,
        port=PORT,
        app_name=APP_NAME,
        place=place,
        guid=guid,
        maybe_slash=includeLastSlash and "/" or "",
        file_path=filePath,
    )
    return path


def getVideoOffset(filename, guid):
    data = {"offset": 0, "date_edited": None}
    try:
        resp = requests.get(
            MEDIAVIEWER_GUID_OFFSET_URL % {"guid": guid, "filename": filename},
            auth=(WAITER_USERNAME, WAITER_PASSWORD),
            verify=VERIFY_REQUESTS,
            timeout=REQUESTS_TIMEOUT,
        )
        resp.raise_for_status()
        resp = resp.json()
        data["offset"] = resp["offset"]
        if "date_edited" in resp:
            data["date_edited"] = resp["date_edited"]
    except Exception as e:
        logger().error(e)
        raise
    return data


def setVideoOffset(filename, guid, offset):
    data = {"offset": offset}
    try:
        resp = requests.post(
            MEDIAVIEWER_GUID_OFFSET_URL % {"guid": guid, "filename": filename},
            auth=(WAITER_USERNAME, WAITER_PASSWORD),
            verify=VERIFY_REQUESTS,
            data=data,
            timeout=REQUESTS_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as e:
        logger().error(e)
        raise


def deleteVideoOffset(filename, guid):
    try:
        resp = requests.delete(
            MEDIAVIEWER_GUID_OFFSET_URL % {"guid": guid, "filename": filename},
            auth=(WAITER_USERNAME, WAITER_PASSWORD),
            verify=VERIFY_REQUESTS,
            timeout=REQUESTS_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as e:
        logger().error(e)
        raise


def getMediaGenres(guid):
    genre_url = MEDIAVIEWER_BASE_URL + f"/ajaxgenres/{guid}/"

    try:
        resp = requests.get(genre_url, timeout=REQUESTS_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger().error(e)
        raise

    data = resp.json()
    tv_genres = [
        (mg[1], MEDIAVIEWER_BASE_URL + f"/tvshows/genre/{mg[0]}/")
        for mg in data["tv_genres"]
    ]
    movie_genres = [
        (mg[1], MEDIAVIEWER_BASE_URL + f"/movies/genre/{mg[0]}/")
        for mg in data["movie_genres"]
    ]
    return tv_genres, movie_genres


def get_collections(guid):
    genre_url = MEDIAVIEWER_BASE_URL + f"/ajaxcollections/{guid}/"
    try:
        resp = requests.get(genre_url, timeout=REQUESTS_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger().error(e)
        raise

    data = resp.json()
    collections = [
        (collection[1], MEDIAVIEWER_BASE_URL + f"/collections/{collection[0]}/")
        for collection in data["collections"]
    ]
    return collections


def hashed_filename(filename):
    peppered_string = filename + SECRET_KEY
    return hashlib.sha256(peppered_string.encode("utf-8")).hexdigest()
