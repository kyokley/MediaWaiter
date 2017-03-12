import os
import mimetypes
from functools import wraps
from flask import (Flask,
                   Response,
                   request,
                   send_file,
                   render_template,
                   jsonify)
from werkzeug.contrib.fixers import ProxyFix
from settings import (BASE_PATH,
                      APP_NAME,
                      MEDIAVIEWER_GUID_URL,
                      MEDIAVIEWER_DOWNLOADCLICK_URL,
                      MEDIAVIEWER_VIEWED_URL,
                      USE_NGINX,
                      WAITER_USERNAME,
                      WAITER_PASSWORD,
                      MEDIAVIEWER_SUFFIX,
                      WAITER_VIEWED_URL,
                      WAITER_OFFSET_URL,
                      VERIFY_REQUESTS,
                      MINIMUM_FILE_SIZE,
                      MEDIAVIEWER_BASE_URL,
                      )
from utils import (humansize,
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

STREAMABLE_FILE_TYPES = ('.mp4',)
SUBTITLE_FILE_TYPES = ('.vtt',)

app = Flask(__name__, static_url_path='')

def logErrorsAndContinue(func):
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        log.debug('Attempting %s' % func.__name__)
        try:
            res = func(*args, **kwargs)
            return res
        except Exception, e:
            log.error(e, exc_info=True)
            errorText = "An error has occurred"
            try:
                token = getTokenByGUID(kwargs.get('guid'))
                username = token['username']
            except:
                username = None
            return render_template("error.html",
                                   title="Error",
                                   errorText=errorText,
                                   mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                                   username=username,
                                   )
    return func_wrapper

def isAlfredEncoding(filename):
    return MEDIAVIEWER_SUFFIX in filename

@delayedRetry(attempts=5, interval=1)
def getTokenByGUID(guid):
    try:
        data = requests.get(MEDIAVIEWER_GUID_URL % {'guid': guid},
                            auth=(WAITER_USERNAME, WAITER_PASSWORD),
                            verify=VERIFY_REQUESTS)
        return data.json()
    except Exception, e:
        log.error(e)
        raise

@delayedRetry()
def updateDownloadClick(userid,
                        tokenid,
                        filename,
                        size):
    values = {'userid': userid,
              'tokenid': tokenid,
              'filename': filename,
              'size': size}
    log.debug(values)

    try:
        req = requests.post(MEDIAVIEWER_DOWNLOADCLICK_URL,
                            data=values,
                            auth=(WAITER_USERNAME, WAITER_PASSWORD),
                            verify=VERIFY_REQUESTS)
        req.raise_for_status()
    except Exception, e:
        log.error(e)

def modifyCookie(resp):
    resp.set_cookie('fileDownload', 'true')
    resp.set_cookie('path', '/')
    return resp

@app.route(APP_NAME + '/dir/<guid>/')
@logErrorsAndContinue
def get_dirPath(guid):
    '''Display a page that lists all media files in a given directory'''
    token = getTokenByGUID(guid)
    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                               )

    files = []
    if token['ismovie']:
        files.extend(buildMovieEntries(token))
    else:
        fileDict = {'path': buildWaiterPath('file', guid, token['path']),
                    'filename': token['filename']}
        files.append(fileDict)
    files.sort()

    tv_genres, movie_genres = getMediaGenres(guid)
    return render_template("display.html",
                           title=token['displayname'],
                           files=files,
                           username=token['username'],
                           mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                           ismovie=token['ismovie'],
                           pathid=token['pathid'],
                           pathname=token['pathname'],
                           guid=guid,
                           offsetUrl=WAITER_OFFSET_URL,
                           next_link=None,
                           previous_link=None,
                           tv_genres=tv_genres,
                           movie_genres=movie_genres,
                           )

def buildMovieEntries(token):
    files = []
    movieFilename = os.path.join(token['path'], token['filename'])
    fullMoviePath = os.path.join(BASE_PATH, movieFilename)
    if os.path.isdir(fullMoviePath):
        for root, subFolders, filenames in os.walk(fullMoviePath):
            for filename in filenames:
                filesDict = _buildFileDictHelper(root, filename, token)
                if filesDict:
                    files.append(filesDict)
    else:
        files.append(_buildFileDictHelper(os.path.dirname(fullMoviePath),
                                          os.path.basename(fullMoviePath),
                                          token))
    return files

def _buildFileDictHelper(root, filename, token):
    path = os.path.join(root, filename)
    size = os.path.getsize(path)
    ext = os.path.splitext(filename)[-1].lower()

    # Files smaller than 10MB probably aren't video files
    if (size < MINIMUM_FILE_SIZE or
            ext not in STREAMABLE_FILE_TYPES or
            not isAlfredEncoding(filename)):
        return None

    waiterPath = os.path.join(token['filename'], filename)
    hashedWaiterPath = hashed_filename(waiterPath)

    streamingPath = buildWaiterPath('stream', token['guid'], hashedWaiterPath, includeLastSlash=True)

    subtitle_file = path[:-4] + '.vtt'
    if os.path.exists(subtitle_file):
        subtitle_basename = os.path.basename(subtitle_file)
        hashedSubtitleFile = hashed_filename(os.path.join(token['filename'], subtitle_basename))
    else:
        subtitle_file = None
        hashedSubtitleFile = None

    fileDict = {'path': buildWaiterPath('file', token['guid'], hashedWaiterPath, includeLastSlash=True),
                'streamingPath': streamingPath,
                'hashedWaiterPath': hashedWaiterPath,
                'unhashedPath': path,
                'streamable': True,
                'filename': filename,
                'size': humansize(size),
                'isAlfredEncoding': True,
                'unhashedSubtitleFile': subtitle_file,
                'subtitleWaiterPath': hashedSubtitleFile and buildWaiterPath('file', token['guid'], hashedSubtitleFile),
                'hashedSubtitleFile': hashedSubtitleFile,
                'ismovie': token['ismovie'],
                'displayName': token['displayname'],
                'hasProgress': hashedWaiterPath in token['videoprogresses']}
    return fileDict

def _getFileEntryFromHash(token, hashPath):
    movieEntries = buildMovieEntries(token)
    for entry in movieEntries:
        if entry['hashedWaiterPath'] == hashPath:
            return entry
        elif entry['hashedSubtitleFile'] == hashPath:
            return {'unhashedPath': entry['unhashedSubtitleFile']}
    else:
        raise Exception('Unable to find matching path')

@app.route(APP_NAME + '/file/<guid>/<path:hashPath>')
@logErrorsAndContinue
def send_file_for_download(guid, hashPath):
    '''Send the file specified at dirPath'''
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                               )

    fullPath = _getFileEntryFromHash(token, hashPath)['unhashedPath']

    filename = os.path.basename(fullPath)
    return send_file_partial(fullPath,
                             filename,
                             token)

@app.route(APP_NAME + '/file/<guid>/')
@logErrorsAndContinue
def get_file(guid):
    '''Display a page that lists a single file'''
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr or token['ismovie']:
        return render_template("error.html",
                               title="Error",
                               errorText='Invalid URL for movie type' if token['ismovie'] else errorStr,
                               mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                               )

    files = buildMovieEntries(token)
    tv_genres, movie_genres = getMediaGenres(guid)
    return render_template("display.html",
                           title=token['displayname'],
                           files=files,
                           username=token['username'],
                           mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                           auto_download=token['auto_download'],
                           ismovie=token['ismovie'],
                           pathid=token['pathid'],
                           pathname=token['pathname'],
                           guid=guid,
                           offsetUrl=WAITER_OFFSET_URL,
                           next_link=token['next_id'] and MEDIAVIEWER_BASE_URL + '/downloadlink/%s/' % token['next_id'],
                           previous_link=token['previous_id'] and MEDIAVIEWER_BASE_URL + '/downloadlink/%s/' % token['previous_id'],
                           tv_genres=tv_genres,
                           movie_genres=movie_genres,
                           )

@app.route(APP_NAME + '/status/', methods=['GET'])
@app.route(APP_NAME + '/status', methods=['GET'])
def get_status():
    res = dict()
    try:
        log.debug('Checking linking')
        moviesLinked = os.path.exists(os.path.join(BASE_PATH, 'Movies'))
        if moviesLinked:
            log.debug('Movies directory is good')
        else:
            log.debug('Movies directory failed')

        tvLinked = os.path.exists(os.path.join(BASE_PATH, 'tv shows'))
        if tvLinked:
            log.debug('tv shows directory is good')
        else:
            log.debug('tv shows directory failed')
        linked = moviesLinked and tvLinked
        log.debug('Result is %s' % linked)

        res['status'] = linked
    except Exception, e:
        log.error(e, exc_info=True)
        print e
        res['status'] = False

    log.debug('status: %s' % (res['status'],))
    return jsonify(res)

@app.after_request
def after_request(response):
    response.headers.add('Accept-Ranges', 'bytes')
    return response

def xsendfile(path, filename, size, range_header=None):
    log.debug('path: %s' % path)
    log.debug('filename: %s' % filename)
    mime = mimetypes.guess_type(path)[0]
    path = path.split('/', 3)[-1]
    redirected_path = '/download/%s' % (path,)
    log.debug('redirected_path is %s' % redirected_path)
    resp = Response(None,
                    206,
                    mimetype=mime,
                    direct_passthrough=True)
    resp.headers['X-Accel-Redirect'] = redirected_path
    resp.headers['Content-Disposition'] = "attachement; filename=%s" % (filename,)

    (length, byte1, byte2) = parseRangeHeaders(size, range_header)
    resp.headers.add('Content-Range', 'bytes {0}-{1}/{2}'.format(byte1, byte1 + length - 1, size))
    log.debug('X-Accel-Redirect: %s' % resp.headers['X-Accel-Redirect'])
    log.debug('Content-Disposition: %s' % resp.headers['Content-Disposition'])
    log.debug('Content-Range: %s' % resp.headers['Content-Range'])
    return resp

def send_file_partial(path,
                      filename,
                      token,
                      test=False):
    range_header = request.headers.get('Range', None)
    size = os.path.getsize(path)

    if not test:
        updateDownloadClick(token['userid'],
                            token['tokenid'],
                            filename,
                            size)
    if USE_NGINX:
        log.debug("Using NGINX to send %s" % filename)
        return xsendfile(path, filename, size, range_header=range_header)
    else:
        return app_sendfile(path, filename, size, range_header=range_header)

def app_sendfile(path,
                 filename,
                 size,
                 range_header=None):
    if not range_header:
        resp = send_file(path,
                         as_attachment=True,
                         attachment_filename=filename)
        return modifyCookie(resp)

    length = byte1 = byte2 = 0
    if range_header:
        (length, byte1, byte2) = parseRangeHeaders(size, range_header)

    data = None
    with open(path, 'rb') as f:
        f.seek(byte1)
        data = f.read(length)

    rv = Response(data,
                  206,
                  mimetype=mimetypes.guess_type(path)[0],
                  direct_passthrough=True)
    rv.headers.add('Content-Range', 'bytes {0}-{1}/{2}'.format(byte1, byte1 + length - 1, size))
    if filename:
        rv.headers['Content-Disposition'] = "attachement; filename=%s" % (filename,)
    else:
        rv.headers['Content-Disposition'] = "attachement;"

    return modifyCookie(rv)

@app.route(APP_NAME + '/stream/<guid>/<path:hashPath>')
@logErrorsAndContinue
def video(guid, hashPath):
    '''Display streaming page'''
    token = getTokenByGUID(guid)

    errorStr = checkForValidToken(token, guid)
    if errorStr:
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                               )

    file_entry = _getFileEntryFromHash(token, hashPath)
    files = buildMovieEntries(token)
    tv_genres, movie_genres = getMediaGenres(guid)

    return render_template('video.html',
                           title=token['displayname'],
                           filename=token['filename'],
                           hashPath=hashPath,
                           video_file=file_entry['path'],
                           subtitle_file=file_entry['subtitleWaiterPath'],
                           viewedUrl=WAITER_VIEWED_URL,
                           offsetUrl=WAITER_OFFSET_URL,
                           guid=guid,
                           username=token['username'],
                           files=files,
                           mediaviewer_base_url=MEDIAVIEWER_BASE_URL,
                           ismovie=token['ismovie'],
                           pathid=token['pathid'],
                           pathname=token['pathname'],
                           next_link=token['next_id'] and MEDIAVIEWER_BASE_URL + '/downloadlink/%s/' % token['next_id'],
                           previous_link=token['previous_id'] and MEDIAVIEWER_BASE_URL + '/downloadlink/%s/' % token['previous_id'],
                           tv_genres=tv_genres,
                           movie_genres=movie_genres,
                           )

@app.route(APP_NAME + '/viewed/<guid>', methods=['POST'])
@app.route(APP_NAME + '/viewed/<guid>/', methods=['POST'])
def ajaxviewed(guid):
    values = {'viewed': True,
              'guid': guid,
              }
    try:
        req = requests.post(MEDIAVIEWER_VIEWED_URL,
                            data=values,
                            auth=(WAITER_USERNAME, WAITER_PASSWORD),
                            verify=VERIFY_REQUESTS,
                            )

        req.raise_for_status()
    except Exception, e:
        log.error(e)
        raise

    return jsonify({'msg': 'Viewed set successfully'})

@app.route(APP_NAME + '/offset/<guid>/<path:hashedFilename>/', methods=['GET', 'POST', 'DELETE'])
def videoOffset(guid, hashedFilename):
    if request.method == 'GET':
        print 'GET-ing video offset'
        data = getVideoOffset(hashedFilename, guid)
        return jsonify(data)
    elif request.method == 'POST':
        print 'POST-ing video offset:'
        print 'offset: %s' % request.form['offset']
        setVideoOffset(hashedFilename, guid, request.form['offset'])
        return jsonify({'msg': 'success'})
    elif request.method == 'DELETE':
        print 'DELETE-ing video offset:'
        deleteVideoOffset(hashedFilename, guid)
        return jsonify({'msg': 'deleted'})
    else:
        raise Exception('Method not supported')

app.wsgi_app = ProxyFix(app.wsgi_app)
if __name__ == '__main__':
    from settings import DEBUG, PORT, HOST
    app.debug = DEBUG
    if not DEBUG:
        app.run(host=HOST, port=PORT)
    else:
        app.run(host=HOST, port=PORT, threaded=True)
