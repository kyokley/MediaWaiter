import os
import mimetypes
import secure

from pathlib import Path
from functools import wraps
from flask import Flask, Response, request, send_file, render_template, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from settings import (
    BASE_PATH,
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
)
from utils import (
    humansize,
    delayedRetry,
    checkForValidToken,
    parseRangeHeaders,
    buildWaiterPath,
    getVideoOffset,
    setVideoOffset,
    deleteVideoOffset,
    hashed_filename,
    getMediaGenres,
)
from log import log
import requests

STREAMABLE_FILE_TYPES = (".mp4",)
SUBTITLE_FILE_TYPES = (".vtt",)

app = Flask(__name__, static_url_path="", static_folder="/var/static")


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
        log.debug(f"Attempting {func.__name__}")
        try:
            res = func(*args, **kwargs)
            return res
        except Exception as e:
            log.error(e, exc_info=True)
            errorText = "An error has occurred"
            try:
                token = getTokenByGUID(kwargs.get("guid"))
                username = token["username"]
            except Exception as e:
                log.error(e)
                username = None
            return (
                render_template(
                    "error.html",
                    title="Error",
                    errorText=errorText,
                    mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
                    username=username,
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
        )
        return data.json()
    except Exception as e:
        log.error(e)
        raise


def modifyCookie(resp):
    resp.set_cookie("fileDownload", "true")
    resp.set_cookie("path", "/")
    return resp


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
        )

    files = []
    if token["ismovie"]:
        files.extend(buildEntries(token))
    else:
        raise ValueError(
            f"Only movies are allowed to display contents of directories. "
            f"GUID = {guid}"
        )
    files.sort(key=lambda x: x["filename"])

    tv_genres, movie_genres = getMediaGenres(guid)
    token = _extract_donation_info(token)
    return render_template(
        "display.html",
        title=token["displayname"],
        files=files,
        username=token["username"],
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        pathid=token["pathid"],
        pathname=token["pathname"],
        guid=guid,
        offsetUrl=WAITER_OFFSET_URL,
        next_link=None,
        previous_link=None,
        tv_genres=tv_genres,
        movie_genres=movie_genres,
        binge_mode=False,
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
    )


def buildEntries(token):
    files = []
    if token["ismovie"]:
        remote_base_path = Path(token["path"]).stem
        fullMoviePath = Path(BASE_PATH) / remote_base_path / token["filename"]

        for root, subFolders, filenames in os.walk(fullMoviePath):
            for filename in filenames:
                filesDict = _buildFileDictHelper(Path(root), filename, token)
                if filesDict:
                    files.append(filesDict)
    else:
        fullMoviePath = (
            Path(BASE_PATH).joinpath(*Path(token["path"]).parts[-2:])
            / token["filename"]
        )
        files.append(
            _buildFileDictHelper(fullMoviePath.parent, fullMoviePath.parts[-1], token)
        )

    return files


def _buildFileDictHelper(root, filename, token):
    path = Path(root) / filename
    size = os.path.getsize(path)
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

    subtitle_file = Path(str(path.parent / path.stem) + ".vtt")
    if subtitle_file.exists():
        subtitle_basename = subtitle_file.name
        hashedSubtitleFile = hashed_filename(
            str(Path(token["filename"]) / subtitle_basename)
        )
    else:
        subtitle_file = None
        hashedSubtitleFile = None

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
        "isAlfredEncoding": True,
        "unhashedSubtitleFile": subtitle_file,
        "subtitleWaiterPath": hashedSubtitleFile
        and buildWaiterPath("file", token["guid"], hashedSubtitleFile),
        "hashedSubtitleFile": hashedSubtitleFile,
        "ismovie": token["ismovie"],
        "displayName": token["displayname"],
        "hasProgress": hashedWaiterPath in token["videoprogresses"],
    }
    return fileDict


def _getFileEntryFromHash(token, hashPath):
    movieEntries = buildEntries(token)
    for entry in movieEntries:
        if entry["hashedWaiterPath"] == hashPath:
            return entry
        elif entry["hashedSubtitleFile"] == hashPath:
            return {"unhashedPath": entry["unhashedSubtitleFile"]}
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
        )

    fullPath = _getFileEntryFromHash(token, hashPath)["unhashedPath"]

    filename = os.path.basename(fullPath)
    return send_file_partial(fullPath, filename, token)


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
        )

    files = buildEntries(token)
    tv_genres, movie_genres = getMediaGenres(guid)
    token = _extract_donation_info(token)
    return render_template(
        "display.html",
        title=token["displayname"],
        files=files,
        username=token["username"],
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        pathid=token["pathid"],
        pathname=token["pathname"],
        guid=guid,
        offsetUrl=WAITER_OFFSET_URL,
        next_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}/downloadlink/{token.get('next_id')}/"
            if token.get("next_id")
            else None
        ),
        previous_link=(
            f"{EXTERNAL_MEDIAVIEWER_BASE_URL}/downloadlink/{token.get('previous_id')}/"
            if token.get("previous_id")
            else None
        ),
        tv_genres=tv_genres,
        movie_genres=movie_genres,
        binge_mode=token["binge_mode"],
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
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
        )

    files = buildEntries(token)
    file_entry = files[0]
    tv_genres, movie_genres = getMediaGenres(guid)
    token = _extract_donation_info(token)
    return render_template(
        "video.html",
        title=token["displayname"],
        filename=token["filename"],
        hashPath=file_entry["hashedWaiterPath"],
        video_file=file_entry["path"],
        subtitle_file=file_entry["subtitleWaiterPath"],
        viewedUrl=WAITER_VIEWED_URL,
        offsetUrl=WAITER_OFFSET_URL,
        guid=guid,
        username=token["username"],
        files=files,
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        pathid=token["pathid"],
        pathname=token["pathname"],
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
        binge_mode=token["binge_mode"],
        CAST_ID=GOOGLE_CAST_APP_ID,
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
    )


def _cli_links(guid):
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return jsonify({"error": errorStr})

    files = buildEntries(token)
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
    try:
        log.debug("Checking linking")
        moviesLinked = os.path.exists(os.path.join(BASE_PATH, "Movies"))
        if moviesLinked:
            log.debug("Movies directory is good")
        else:
            log.debug("Movies directory failed")

        tvLinked = os.path.exists(os.path.join(BASE_PATH, "tv shows"))
        if tvLinked:
            log.debug("tv shows directory is good")
        else:
            log.debug("tv shows directory failed")
        linked = moviesLinked and tvLinked
        log.debug(f"Result is {linked}")

        res["status"] = linked
    except Exception as e:
        log.error(e, exc_info=True)
        res["status"] = False

    log.debug(f'status: {res["status"]}')
    return res, 200 if res["status"] else 500


@app.after_request
def after_request(response):
    response.headers.add("Accept-Ranges", "bytes")
    return response


def xsendfile(path, filename, size, range_header=None):
    path = str(path)

    log.debug(f"path: {path}")
    log.debug(f"filename: {filename}")
    mime = mimetypes.guess_type(path)[0]
    path = path.split("/", 3)[-1]
    redirected_path = f"/download/{path}"
    log.debug(f"redirected_path is {redirected_path}")
    resp = Response(None, 206, mimetype=mime, direct_passthrough=True)
    resp.headers["X-Accel-Redirect"] = redirected_path
    resp.headers["Content-Disposition"] = f"attachement; filename={filename}"

    (length, byte1, byte2) = parseRangeHeaders(size, range_header)
    resp.headers.add("Content-Range", f"bytes {byte1}-{byte2}/{size}")
    log.debug(f'X-Accel-Redirect: {resp.headers["X-Accel-Redirect"]}')
    log.debug(f'Content-Disposition: {resp.headers["Content-Disposition"]}')
    log.debug(f'Content-Range: {resp.headers["Content-Range"]}')
    return resp


def send_file_partial(path, filename, token, test=False):
    range_header = request.headers.get("Range", None)
    size = os.path.getsize(path)

    if USE_NGINX:
        log.debug(f"Using NGINX to send {filename}")
        return xsendfile(path, filename, size, range_header=range_header)
    else:
        return app_sendfile(path, filename, size, range_header=range_header)


def app_sendfile(path, filename, size, range_header=None):
    path = str(path)
    if not range_header:
        resp = send_file(path, as_attachment=True, attachment_filename=filename)
        return modifyCookie(resp)

    length = byte1 = byte2 = 0
    if range_header:
        (length, byte1, byte2) = parseRangeHeaders(size, range_header)

    data = None
    with open(path, "rb") as f:
        f.seek(byte1)
        data = f.read(length)

    rv = Response(
        data, 206, mimetype=mimetypes.guess_type(path)[0], direct_passthrough=True
    )
    rv.headers.add("Content-Range", f"bytes {byte1}-{byte2}/{size}")
    if filename:
        rv.headers["Content-Disposition"] = f"attachement; filename={filename}"
    else:
        rv.headers["Content-Disposition"] = "attachement;"

    return modifyCookie(rv)


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
        )

    file_entry = _getFileEntryFromHash(token, hashPath)
    files = buildEntries(token)
    tv_genres, movie_genres = getMediaGenres(guid)

    token = _extract_donation_info(token)
    return render_template(
        "video.html",
        title=token["displayname"],
        filename=token["filename"],
        hashPath=hashPath,
        video_file=file_entry["path"],
        subtitle_file=file_entry["subtitleWaiterPath"],
        viewedUrl=WAITER_VIEWED_URL,
        offsetUrl=WAITER_OFFSET_URL,
        guid=guid,
        username=token["username"],
        files=files,
        mediaviewer_base_url=EXTERNAL_MEDIAVIEWER_BASE_URL,
        ismovie=token["ismovie"],
        pathid=token["pathid"],
        pathname=token["pathname"],
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
        binge_mode=token["binge_mode"],
        CAST_ID=GOOGLE_CAST_APP_ID,
        donation_site_name=token.get("donation_site_name"),
        donation_site_url=token.get("donation_site_url"),
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
        )

        req.raise_for_status()
    except Exception as e:
        log.error(e)
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
        print(f'offset: {request.form["offset"]}')
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
