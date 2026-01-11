import os
import secure
import jwt
import random
import string
import re

from collections import namedtuple
from pathlib import Path
from functools import wraps
from flask import Flask, request, send_file, render_template, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
from settings import (
    BASE_PATH,
    MEDIA_DIRS,
    APP_NAME,
    MEDIAVIEWER_GUID_URL,
    MEDIAVIEWER_VIEWED_URL,
    USE_NGINX,
    WAITER_USERNAME,
    WAITER_PASSWORD,
    MEDIAVIEWER_SUFFIX,
    WAITER_VIEWED_URL,
    WAITER_OFFSET_URL,
    VERIFY_REQUESTS,
    MINIMUM_FILE_SIZE,
    EXTERNAL_MEDIAVIEWER_BASE_URL,
    GOOGLE_CAST_APP_ID,
    REQUESTS_TIMEOUT,
    DEFAULT_THEME,
    JITSI_JWT_APP_ID,
    JITSI_JWT_APP_SECRET,
    JITSI_JWT_SUB,
)
from utils import (
    humansize,
    delayedRetry,
    checkForValidToken,
    buildWaiterPath,
    getVideoOffset,
    setVideoOffset,
    deleteVideoOffset,
    hashed_filename,
    getMediaGenres,
    get_collections,
)
from log import logger
import requests

rand = random.SystemRandom()

ROOM_NAME_CHARS = string.ascii_letters + string.digits
ROOM_NAME_LENGTH = 20

Subtitle = namedtuple("Subtitle", "path,hashed_filename,waiter_path")
STREAMABLE_FILE_TYPES = (".mp4",)

app = Flask(__name__, static_url_path="/static", static_folder="/var/static")


secure_headers = secure.Secure()


@app.after_request
def set_secure_headers(response):
    secure_headers.framework.flask(response)
    return response


def _extract_donation_info(token):
    donation_site = token.get("donation_site")
    if donation_site:
        token["donation_site_name"] = donation_site["site_name"]
        token["donation_site_url"] = donation_site["url"]
    else:
        token["donation_site_name"] = ""
        token["donation_site_url"] = ""
    return token


def logErrorsAndContinue(func):
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        logger().debug(f"Attempting {func.__name__}")
        token = None
        try:
            res = func(*args, **kwargs)
            return res
        except Exception as e:
            logger().error(e, exc_info=True)
            errorText = "An error has occurred"
            try:
                token = getTokenByGUID(kwargs.get("guid"))
            except Exception as e:
                logger().error(e)

            username = token.get("username") if token else None
            theme = token.get("theme", DEFAULT_THEME) if token else DEFAULT_THEME
            return (
                render_template(
                    "error.html",
                    title="Error",
                    errorText=errorText,
                    mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
                    username=username,
                    theme=theme,
                ),
                400,
            )

    return func_wrapper


def isAlfredEncoding(filename):
    return MEDIAVIEWER_SUFFIX.lower() in filename.lower()


@delayedRetry(attempts=5, interval=1)
def getTokenByGUID(guid):
    try:
        data = requests.get(
            MEDIAVIEWER_GUID_URL % {"guid": guid},
            auth=(WAITER_USERNAME, WAITER_PASSWORD),
            verify=VERIFY_REQUESTS,
            timeout=REQUESTS_TIMEOUT,
        )
        return data.json()
    except Exception as e:
        logger().error(e)
        raise


@app.route(APP_NAME + "/dir/<guid>/")
@logErrorsAndContinue
def get_dirPath(guid):
    """Display a page that lists all media files in a given directory"""
    token = getTokenByGUID(guid)
    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return render_template(
            "error.html",
            title="Error",
            errorText=errorStr,
            mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
            theme=token.get("theme", DEFAULT_THEME),
        )

    files = []
    if token["ismovie"]:
        files.extend(buildEntries(token))
    else:
        raise ValueError(
            f"Only movies are allowed to display contents of directories. GUID = {guid}"
        )
    files.sort(key=lambda x: x["filename"])

    tv_genres, movie_genres = getMediaGenres(guid)
    collections = get_collections(guid)
    token = _extract_donation_info(token)
    return render_template(
        "display.html",
        title=token["displayname"],
        files=files,
        username=token["username"],
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        tv_id=token["tv_id"],
        tv_name=token["tv_name"],
        guid=guid,
        offsetUrl=WAITER_OFFSET_URL,
        next_link=None,
        previous_link=None,
        tv_genres=tv_genres,
        movie_genres=movie_genres,
        collections=collections,
        binge_mode=False,
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
        theme=token.get("theme", DEFAULT_THEME),
    )


def buildEntries(token):
    if token["ismovie"]:
        fullMoviePath = Path(token["path"])

        for root, subFolders, filenames in os.walk(fullMoviePath):
            for filename in filenames:
                filesDict = _buildFileDictHelper(Path(root), filename, token)
                if filesDict:
                    yield filesDict
    else:
        fullMoviePath = (
            Path(BASE_PATH).joinpath(*Path(token["path"]).parts[-2:])
            / token["filename"]
        )
        yield _buildFileDictHelper(fullMoviePath.parent, fullMoviePath.parts[-1], token)


def _buildFileDictHelper(root, filename, token):
    path = Path(root) / filename
    size = path.stat().st_size
    ext = path.suffix.lower()

    # Files smaller than 10MB probably aren't video files
    if (
        size < MINIMUM_FILE_SIZE
        or ext not in STREAMABLE_FILE_TYPES
        or not isAlfredEncoding(filename)
    ):
        return None

    waiterPath = Path(token["filename"]) / filename
    hashedWaiterPath = hashed_filename(str(waiterPath))

    streamingPath = buildWaiterPath(
        "stream", token["guid"], hashedWaiterPath, includeLastSlash=True
    )

    subtitle_files = []
    for subtitle_file in path.parent.glob("*.vtt"):
        if str(Path(filename).stem) in str(subtitle_file):
            hashedSubtitleFile = hashed_filename(
                str(Path(token["filename"]) / subtitle_file.name)
            )
            subtitle = Subtitle(
                path=subtitle_file,
                hashed_filename=hashedSubtitleFile,
                waiter_path=buildWaiterPath("file", token["guid"], hashedSubtitleFile),
            )
            subtitle_files.append(subtitle)

    fileDict = {
        "path": buildWaiterPath(
            "file", token["guid"], hashedWaiterPath, includeLastSlash=True
        ),
        "streamingPath": streamingPath,
        "hashedWaiterPath": hashedWaiterPath,
        "unhashedPath": path,
        "streamable": True,
        "filename": filename.split("." + MEDIAVIEWER_SUFFIX)[0],
        "size": humansize(size),
        "rawSize": size,
        "isAlfredEncoding": True,
        "subtitleFiles": subtitle_files,
        "ismovie": token["ismovie"],
        "displayName": token["displayname"],
        "hasProgress": hashedWaiterPath in token["videoprogresses"],
    }
    return fileDict


def _getFileEntryFromHash(token, hashPath):
    entries = buildEntries(token)
    for entry in entries:
        if entry["hashedWaiterPath"] == hashPath:
            return entry

        for subtitle in entry["subtitleFiles"]:
            if subtitle.hashed_filename == hashPath:
                unhashed_path = Path(subtitle.path)
                size = unhashed_path.stat().st_size
                return {"unhashedPath": subtitle.path, "rawSize": size}
    else:
        raise Exception("Unable to find matching path")


@app.route(APP_NAME + "/file/<guid>/<path:hashPath>")
@logErrorsAndContinue
def send_file_for_download(guid, hashPath):
    """Send the file specified at dirPath"""
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return render_template(
            "error.html",
            title="Error",
            errorText=errorStr,
            mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
            theme=token.get("theme", DEFAULT_THEME),
        )

    entry = _getFileEntryFromHash(token, hashPath)
    fullPath = entry["unhashedPath"]
    return send_file_partial(fullPath, fullPath.name, entry["rawSize"])


@app.route(APP_NAME + "/file/<guid>/")
@logErrorsAndContinue
def get_file(guid):
    """Display a page that lists a single file"""
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr or token["ismovie"]:
        return render_template(
            "error.html",
            title="Error",
            errorText=("Invalid URL for movie type" if token["ismovie"] else errorStr),
            mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
            theme=token.get("theme", DEFAULT_THEME),
        )

    files = list(buildEntries(token))
    tv_genres, movie_genres = getMediaGenres(guid)
    collections = get_collections(guid)
    token = _extract_donation_info(token)
    return render_template(
        "display.html",
        title=token["displayname"],
        files=files,
        username=token["username"],
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        tv_id=token["tv_id"],
        tv_name=token["tv_name"],
        guid=guid,
        offsetUrl=WAITER_OFFSET_URL,
        next_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}/autoplaydownloadlink/{token.get('next_id')}/"
            if token.get("next_id")
            else None
        ),
        previous_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}/autoplaydownloadlink/{token.get('previous_id')}/"
            if token.get("previous_id")
            else None
        ),
        tv_genres=tv_genres,
        movie_genres=movie_genres,
        collections=collections,
        binge_mode=token["binge_mode"],
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
        theme=token.get("theme", DEFAULT_THEME),
    )


@app.route(APP_NAME + "/file/<guid>/autoplay")
@logErrorsAndContinue
def autoplay(guid):
    """Autoplay a single file"""
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr or token["ismovie"]:
        return render_template(
            "error.html",
            title="Error",
            errorText=("Invalid URL for movie type" if token["ismovie"] else errorStr),
            mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
            theme=token.get("theme", DEFAULT_THEME),
        )

    files = list(buildEntries(token))
    file_entry = files[0]
    tv_genres, movie_genres = getMediaGenres(guid)
    collections = get_collections(guid)
    token = _extract_donation_info(token)

    watch_party_url = get_watch_party_url(
        guid, file_entry["hashedWaiterPath"], token["username"]
    )

    return render_template(
        "video.html",
        title=token["displayname"],
        filename=token["filename"],
        hashPath=file_entry["hashedWaiterPath"],
        video_file=file_entry["path"],
        subtitle_files=[
            subtitle.waiter_path for subtitle in file_entry["subtitleFiles"]
        ],
        viewedUrl=WAITER_VIEWED_URL,
        offsetUrl=WAITER_OFFSET_URL,
        guid=guid,
        username=token["username"],
        files=files,
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        tv_id=token["tv_id"],
        tv_name=token["tv_name"],
        next_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}"
            f"/autoplaydownloadlink/{token.get('next_id')}/"
            if token.get("next_id")
            else None
        ),
        previous_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}"
            f"/autoplaydownloadlink/{token.get('previous_id')}"
            if token.get("previous_id")
            else None
        ),
        tv_genres=tv_genres,
        movie_genres=movie_genres,
        collections=collections,
        binge_mode=token["binge_mode"],
        CAST_ID=GOOGLE_CAST_APP_ID,
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
        theme=token.get("theme", DEFAULT_THEME),
        watch_party_url=watch_party_url,
    )


def get_watch_party_url(guid, hashPath, username):
    return (
        f"{APP_NAME}/watch-party/{guid}/{hashPath}"
        if JITSI_JWT_APP_ID and JITSI_JWT_APP_SECRET and JITSI_JWT_SUB
        else ""
    )


def _cli_links(guid):
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return jsonify({"error": errorStr})

    files = list(buildEntries(token))
    file_entry = files[0]

    return jsonify(
        {
            "video_link": file_entry["path"],
            "subtitle_link": file_entry["subtitleWaiterPath"],
        }
    )


@app.route(APP_NAME + "/file/<guid>/cli/")
@logErrorsAndContinue
def tv_cli_links(guid):
    return _cli_links(guid)


@app.route(APP_NAME + "/dir/<guid>/cli/")
@logErrorsAndContinue
def movie_cli_links(guid):
    return _cli_links(guid)


@app.route(APP_NAME + "/status/", methods=["GET"])
@app.route(APP_NAME + "/status", methods=["GET"])
def get_status():
    res = dict()
    base_path = Path(BASE_PATH)

    try:
        logger().debug("Checking linking")
        linked = True
        for dir in MEDIA_DIRS:
            media_path = base_path / dir
            if media_path.exists():
                logger().debug(f"{media_path} directory is good")
            else:
                logger().debug(f"{media_path} directory failed")
                linked = False

        logger().debug(f"Result is {linked}")

        res["status"] = linked
    except Exception as e:
        logger().error(e, exc_info=True)
        res["status"] = False

    logger().debug(f"status: {res['status']}")
    return res, 200 if res["status"] else 500


@app.after_request
def after_request(response):
    response.headers.add("Accept-Ranges", "bytes")
    return response


def xsendfile(path, filename, size):
    path = str(path)

    logger().debug(f"path: {path}")
    logger().debug(f"filename: {filename}")
    redirected_path = f"/download/{path.split('/', 3)[-1]}"
    logger().debug(f"redirected_path is {redirected_path}")
    # resp = send_file(path, conditional=True)

    range_header = request.headers.get("Range", "0-")

    # Look up for ranges
    m = re.search(r"(\d+)-(\d*)", range_header)
    g = m.groups()
    byte1, byte2 = 0, None
    if g[0]:
        byte1 = int(g[0])
    if g[1]:
        byte2 = int(g[1])
    else:
        byte2 = size - 1

    if size < byte2:
        byte2 = size - 1

    length = byte2 - byte1 + 1

    resp = Response(None, 206)
    resp.headers.add(
        "Content-Range",
        "bytes {0}-{1}/{2}".format(byte1, byte1 + length - 1, size),
    )

    resp.headers["Content-Length"] = str(length)
    resp.headers["Content-Type"] = "video/mp4"
    resp.headers["X-Accel-Redirect"] = redirected_path
    resp.headers["X-Accel-Buffering"] = "no"

    logger().debug(f"X-Accel-Redirect: {resp.headers['X-Accel-Redirect']}")
    logger().debug(f"X-Accel-Buffering: {resp.headers['X-Accel-Buffering']}")
    return resp


def send_file_partial(path, filename, size):
    if USE_NGINX:
        logger().debug(f"Using NGINX to send {filename}")
        return xsendfile(path, filename, size)
    else:
        logger().debug(f"Using Flask to send {filename}")
        return send_file(path, conditional=True)


@app.route(APP_NAME + "/stream/<guid>/<path:hashPath>")
@logErrorsAndContinue
def video(guid, hashPath):
    """Display streaming page"""
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return render_template(
            "error.html",
            title="Error",
            errorText=errorStr,
            mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
            theme=token.get("theme", DEFAULT_THEME),
        )

    file_entry = _getFileEntryFromHash(token, hashPath)
    files = list(buildEntries(token))
    tv_genres, movie_genres = getMediaGenres(guid)
    collections = get_collections(guid)

    token = _extract_donation_info(token)

    watch_party_url = get_watch_party_url(guid, hashPath, token["username"])

    return render_template(
        "video.html",
        title=token["displayname"],
        filename=token["filename"],
        hashPath=hashPath,
        video_file=file_entry["path"],
        subtitle_files=[
            subtitle.waiter_path for subtitle in file_entry["subtitleFiles"]
        ],
        viewedUrl=WAITER_VIEWED_URL,
        offsetUrl=WAITER_OFFSET_URL,
        guid=guid,
        username=token["username"],
        files=files,
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        tv_id=token["tv_id"],
        tv_name=token["tv_name"],
        next_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}"
            f"/autoplaydownloadlink/{token.get('next_id')}/"
            if token.get("next_id")
            else None
        ),
        previous_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}"
            f"/autoplaydownloadlink/{token.get('previous_id')}/"
            if token.get("previous_id")
            else None
        ),
        tv_genres=tv_genres,
        movie_genres=movie_genres,
        collections=collections,
        binge_mode=token["binge_mode"],
        CAST_ID=GOOGLE_CAST_APP_ID,
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
        theme=token.get("theme", DEFAULT_THEME),
        watch_party_url=watch_party_url,
    )


def get_jitsi_room_name():
    chars = [rand.choice(ROOM_NAME_CHARS) for x in range(ROOM_NAME_LENGTH)]
    return "".join(chars)


@app.route(APP_NAME + "/watch-party/<guid>/<path:hashPath>")
@logErrorsAndContinue
def watch_party(guid, hashPath):
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return render_template(
            "error.html",
            title="Error",
            errorText=errorStr,
            mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
            theme=token.get("theme", DEFAULT_THEME),
        )

    file_entry = _getFileEntryFromHash(token, hashPath)
    files = list(buildEntries(token))
    tv_genres, movie_genres = getMediaGenres(guid)
    collections = get_collections(guid)

    token = _extract_donation_info(token)

    jitsi_payload = {
        "context": {"user": {"name": token["username"], "email": token["username"]}},
        "aud": JITSI_JWT_APP_ID,
        "iss": JITSI_JWT_APP_ID,
        "sub": JITSI_JWT_SUB,
        "room": "*",
    }
    encoded_jwt = jwt.encode(
        jitsi_payload,
        JITSI_JWT_APP_SECRET,
    )
    watch_party_room_name = get_jitsi_room_name()
    if token["ismovie"]:
        video_stream_url = f"{APP_NAME}/dir/{guid}/"
    else:
        video_stream_url = f"{APP_NAME}/file/{guid}/"
    return render_template(
        "watch_party.html",
        title=token["displayname"],
        filename=token["filename"],
        hashPath=hashPath,
        video_file=file_entry["path"],
        subtitle_files=[
            subtitle.waiter_path for subtitle in file_entry["subtitleFiles"]
        ],
        viewedUrl=WAITER_VIEWED_URL,
        offsetUrl=WAITER_OFFSET_URL,
        guid=guid,
        username=token["username"],
        files=files,
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        tv_id=token["tv_id"],
        tv_name=token["tv_name"],
        next_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}"
            f"/autoplaydownloadlink/{token.get('next_id')}/"
            if token.get("next_id")
            else None
        ),
        previous_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}"
            f"/autoplaydownloadlink/{token.get('previous_id')}/"
            if token.get("previous_id")
            else None
        ),
        tv_genres=tv_genres,
        movie_genres=movie_genres,
        collections=collections,
        binge_mode=token["binge_mode"],
        CAST_ID=GOOGLE_CAST_APP_ID,
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
        theme=token.get("theme", DEFAULT_THEME),
        jitsi_jwt=encoded_jwt,
        watch_party_room_name=watch_party_room_name,
        video_stream_url=video_stream_url,
    )


@app.route(APP_NAME + "/viewed/<guid>", methods=["POST"])
@app.route(APP_NAME + "/viewed/<guid>/", methods=["POST"])
def ajaxviewed(guid):
    values = {
        "viewed": True,
        "guid": guid,
    }
    try:
        req = requests.post(
            MEDIAVIEWER_VIEWED_URL,
            data=values,
            auth=(WAITER_USERNAME, WAITER_PASSWORD),
            verify=VERIFY_REQUESTS,
            timeout=REQUESTS_TIMEOUT,
        )

        req.raise_for_status()
    except Exception as e:
        logger().error(e)
        raise

    return jsonify({"msg": "Viewed set successfully"})


@app.route(
    APP_NAME + "/offset/<guid>/<path:hashedFilename>/",
    methods=["GET", "POST", "DELETE"],
)
def videoOffset(guid, hashedFilename):
    if request.method == "GET":
        print("GET-ing video offset")
        data = getVideoOffset(hashedFilename, guid)
        return jsonify(data)
    elif request.method == "POST":
        print("POST-ing video offset:")
        print(f"offset: {request.form['offset']}")
        setVideoOffset(hashedFilename, guid, request.form["offset"])
        return jsonify({"msg": "success"})
    elif request.method == "DELETE":
        print("DELETE-ing video offset:")
        deleteVideoOffset(hashedFilename, guid)
        return jsonify({"msg": "deleted"})
    else:
        raise Exception("Method not supported")


app.wsgi_app = ProxyFix(app.wsgi_app)
if __name__ == "__main__":
    from settings import DEBUG, PORT, HOST

    app.debug = DEBUG
    if not DEBUG:
        app.run(host=HOST, port=PORT)
    else:
        app.run(host=HOST, port=PORT, threaded=True)
else:
    gunicorn_app = app
