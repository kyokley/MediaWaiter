import os
import mimetypes
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
                      )
from utils import (humansize,
                   delayedRetry,
                   logErrorsAndContinue,
                   checkForValidToken,
                   parseRangeHeaders,
                   buildWaiterPath,
                   getVideoOffset,
                   setVideoOffset,
                   deleteVideoOffset,
                   )
from log import log
import requests

STREAMABLE_FILE_TYPES = ('.mp4',)

app = Flask(__name__, static_url_path='')

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
    try:
        res = getTokenByGUID(guid)
    except Exception, e:
        log.debug(e, exc_info=True)
        errorText = "An error has occurred"
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               )

    errorStr = checkForValidToken(res, guid)
    if errorStr:
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               )

    try:
        files = []
        if res['ismovie']:
            moviePath = os.path.join(res['path'], res['filename'])
            files.extend(buildMovieEntries(guid, moviePath))
        else:
            fileDict = {'path': buildWaiterPath('file', guid, res['path']),
                        'filename': res['filename']}
            files.append(fileDict)
        files.sort()
        return render_template("display.html",
                               title=res['displayname'],
                               files=files,
                               )
    except Exception, e:
        log.debug(e, exc_info=True)
        errorText = "An error has occurred"
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               )

def buildMovieEntries(guid, movieFilename):
    files = []
    searchPath = os.path.join(BASE_PATH, movieFilename)
    for root, subFolders, filenames in os.walk(searchPath):
        for filename in filenames:
            path = os.path.join(root, filename)
            size = os.path.getsize(path)

            waiterPath = path.partition(searchPath)[2][1:]

            # Files smaller than 10MB probably aren't video files
            if size < 10000000:
                continue
            ext = os.path.splitext(filename)[-1].lower()
            streamingPath = (ext in STREAMABLE_FILE_TYPES and
                             buildWaiterPath('stream', guid, waiterPath, includeLastSlash=True) or
                             None)
            fileDict = {'path': buildWaiterPath('file', guid, waiterPath, includeLastSlash=True),
                        'streamingPath': streamingPath,
                        'streamable': bool(streamingPath),
                        'filename': filename,
                        'size': humansize(size),
                        'isAlfredEncoding': isAlfredEncoding(filename),
                        'ismovie': True}
            files.append(fileDict)
    return files

@app.route(APP_NAME + '/file/<guid>/<path:filePath>')
@logErrorsAndContinue
def send_file_for_download(guid, filePath):
    '''Send the file specified at dirPath'''
    try:
        res = getTokenByGUID(guid)
    except Exception, e:
        log.debug(e, exc_info=True)
        errorText = "An error has occurred"
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               )

    errorStr = checkForValidToken(res, guid)
    if errorStr:
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               )

    if res['ismovie']:
        fullPath = os.path.join(BASE_PATH, res['path'], res['filename'], filePath)
    else:
        fullPath = os.path.join(res['path'], filePath)

    if (res and
            res['path'] in fullPath and
            '..' not in filePath):
        path, filename = os.path.split(fullPath)
        return send_file_partial(fullPath,
                                 filename=filename,
                                 token=res)
    else:
        log.error('Unauthorized use of GUID attempted')
        log.error('GUID: %s' % (guid,))
        errorText = 'Access is unauthorized!'
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               )

@app.route(APP_NAME + '/file/<guid>/')
@logErrorsAndContinue
def get_file(guid):
    '''Display a page that lists a single file'''
    try:
        res = getTokenByGUID(guid)
    except Exception, e:
        log.debug(e, exc_info=True)
        errorText = "An error has occurred"
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               )

    errorStr = checkForValidToken(res, guid)
    if errorStr or res['ismovie']:
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               )

    ext = os.path.splitext(res['filename'])[-1].lower()
    streamingPath = (ext in STREAMABLE_FILE_TYPES and
                     buildWaiterPath('stream', guid, res['filename']) or
                     None)

    fullPath = os.path.join(res['path'], res['filename'])
    if not os.path.exists(fullPath):
        log.error('File %s does not exists' % fullPath)
        errorText = 'An error has occurred'
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               )

    files = []
    fileDict = {'path': buildWaiterPath('file', guid, res['filename']),
                'streamingPath': streamingPath,
                'streamable': bool(streamingPath),
                'size': humansize(os.path.getsize(fullPath)),
                'filename': res['filename'],
                'displayName': res['displayname'],
                'isAlfredEncoding': isAlfredEncoding(res['filename']),
                'ismovie': False}
    files.append(fileDict)
    return render_template("display.html",
                           title=res['displayname'],
                           files=files,
                           auto_download=res['auto_download'])

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
                      filename=None,
                      token=None,
                      test=False):
    range_header = request.headers.get('Range', None)
    size = os.path.getsize(path)
    length = byte1 = byte2 = 0
    if range_header:
        (length, byte1, byte2) = parseRangeHeaders(size, range_header)

    if not test:
        updateDownloadClick(token['userid'],
                            token['tokenid'],
                            filename,
                            length or size)
    if USE_NGINX:
        log.debug("Using NGINX to send %s" % filename)
        return xsendfile(path, filename, size, range_header=range_header)
    else:
        if not range_header:
            resp = send_file(path,
                             as_attachment=True,
                             attachment_filename=filename)
            return modifyCookie(resp)

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

@app.route(APP_NAME + '/stream/<guid>/<path:dirPath>')
def video(guid, dirPath):
    '''Display streaming page'''
    try:
        res = getTokenByGUID(guid)
    except Exception, e:
        log.debug(e, exc_info=True)
        errorText = "An error has occurred"
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               )

    errorStr = checkForValidToken(res, guid)

    if res['ismovie']:
        filePath = os.path.join(BASE_PATH, res['path'], res['filename'], dirPath)
    else:
        filePath = os.path.join(BASE_PATH, res['path'], dirPath)

    if (not errorStr and
            (not os.path.exists(filePath) or
                '..' in dirPath)):
        errorStr = 'Bad path or filename'

    if errorStr:
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               )

    fullPath = buildWaiterPath('file', guid, dirPath, includeLastSlash=True)


    subtitle_filename = filePath[:-4] + '.vtt'
    subtitle_file = fullPath[:-4] + '.vtt' if os.path.exists(subtitle_filename) else None

    return render_template('video.html',
                           title=res['displayname'],
                           filename=res['filename'],
                           dirPath=dirPath,
                           video_file=fullPath,
                           subtitle_file=subtitle_file,
                           viewedUrl=WAITER_VIEWED_URL,
                           offsetUrl=WAITER_OFFSET_URL,
                           guid=guid,
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

@app.route(APP_NAME + '/offset/<guid>/<path:filename>/', methods=['GET', 'POST', 'DELETE'])
def videoOffset(guid, filename):
    if request.method == 'GET':
        print 'GET-ing video offset'
        data = getVideoOffset(filename, guid)
        return jsonify(data)
    elif request.method == 'POST':
        print 'POST-ing video offset:'
        print 'offset: %s' % request.form['offset']
        setVideoOffset(filename, guid, request.form['offset'])
        return jsonify({'msg': 'success'})
    elif request.method == 'DELETE':
        print 'DELETE-ing video offset:'
        deleteVideoOffset(filename, guid)
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
        app.run(port=PORT, threaded=True)
