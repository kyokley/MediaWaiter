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
                      )
from utils import (humansize,
                   delayedRetry,
                   logErrorsAndContinue,
                   checkForValidToken,
                   parseRangeHeaders,
                   buildWaiterPath,
                   )
from log import log
import urllib
import urllib2
import json
import base64


STREAMABLE_FILE_TYPES = ('.mp4',)

app = Flask(__name__, static_url_path='')

def isAlfredEncoding(filename):
    return MEDIAVIEWER_SUFFIX in filename

@delayedRetry(attempts=5, interval=1)
def getTokenByGUID(guid):
    try:
        url = urllib2.urlopen(MEDIAVIEWER_GUID_URL % {'guid': guid}, timeout=2)
        data = json.load(url)
        return data
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
    data = urllib.urlencode(values)
    base64string = base64.encodestring('%s:%s' % (WAITER_USERNAME, WAITER_PASSWORD)).replace('\n', '')
    auth_header = 'Basic %s' % base64string
    log.debug(auth_header)
    req = urllib2.Request(MEDIAVIEWER_DOWNLOADCLICK_URL, data)
    req.add_header("Authorization", auth_header)

    try:
        urllib2.urlopen(req)
    except urllib2.HTTPError, e:
        log.error(e.code)
        log.error(e.read())
        raise

def modifyCookie(resp):
    resp.set_cookie('fileDownload', 'true')
    resp.set_cookie('path', '/')
    return resp

@app.route(APP_NAME + '/dir/<guid>/')
@logErrorsAndContinue
def get_dirPath(guid):
    '''Display a page that lists all media files in a given directory'''
    res = getTokenByGUID(guid)

    errorStr = checkForValidToken(res, guid)
    if errorStr:
        theme = res and res.get('waitertheme') or None
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               theme=theme)

    try:
        files = []
        if res['ismovie']:
            files.extend(buildMovieEntries(guid, res['path']))
        else:
            fileDict = {'path': buildWaiterPath('file', guid, res['path']),
                        'filename': res['filename']}
            files.append(fileDict)
        theme = res['waitertheme'] or None
        return render_template("display.html",
                               title=res['displayname'],
                               files=files,
                               theme=theme)
    except Exception, e:
        log.debug(e, exc_info=True)
        theme = res and res.get('waitertheme') or None
        errorText = "An error has occurred"
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               theme=theme)

def buildMovieEntries(guid, moviePath):
    files = []
    searchPath = os.path.join(BASE_PATH, moviePath)
    for root, subFolders, filenames in os.walk(searchPath):
        for filename in filenames:
            path = os.path.join(root, filename)
            size = os.path.getsize(path)

            waiterPath = path[1:]

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

@app.route(APP_NAME + '/file/<guid>/<path:dirPath>')
@logErrorsAndContinue
def get_file(guid, dirPath):
    '''Send the file specified at dirPath'''
    res = getTokenByGUID(guid)
    errorStr = checkForValidToken(res, guid)
    if errorStr:
        theme = res and res.get('waitertheme') or None
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               theme=theme)

    fullPath = os.path.join('/', dirPath)

    if res and res['path'] in fullPath:
        path, filename = os.path.split(fullPath)
        return send_file_partial(fullPath,
                                 filename=filename,
                                 token=res)
    else:
        log.error('Unauthorized use of GUID attempted')
        log.error('GUID: %s' % (guid,))
        errorText = 'Access is unauthorized!'
        theme = res and res.get('waitertheme') or None
        return render_template("error.html",
                               title="Error",
                               errorText=errorText,
                               theme=theme)

@app.route(APP_NAME + '/file/<guid>/')
@logErrorsAndContinue
def get_file2(guid):
    '''Display a page that lists a single file'''
    res = getTokenByGUID(guid)
    errorStr = checkForValidToken(res, guid)
    if errorStr:
        theme = res and res.get('waitertheme') or None
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               theme=theme)

    ext = os.path.splitext(res['path'])[-1].lower()
    streamingPath = (ext in STREAMABLE_FILE_TYPES and
                     buildWaiterPath('stream', guid, res['path']) or
                     None)
    files = []
    fileDict = {'path': buildWaiterPath('file', guid, res['path']),
                'streamingPath': streamingPath,
                'streamable': bool(streamingPath),
                'size': humansize(os.path.getsize(res['path'])),
                'filename': res['filename'],
                'displayName': res['displayname'],
                'ismovie': False}
    files.append(fileDict)
    theme = res['waitertheme'] or None
    return render_template("display.html",
                           title=res['displayname'],
                           files=files,
                           theme=theme)

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
    res = getTokenByGUID(guid)
    errorStr = checkForValidToken(res, guid)
    if errorStr:
        theme = res and res.get('waitertheme') or None
        return render_template("error.html",
                               title="Error",
                               errorText=errorStr,
                               theme=theme)

    fullPath = buildWaiterPath('file', guid, dirPath, includeLastSlash=True)

    theme = res and res.get('waitertheme') or None
    path, filename = os.path.split(fullPath)
    return render_template('video.html',
                           title=res['displayname'],
                           filename=res['filename'],
                           video_file=fullPath,
                           viewedUrl=MEDIAVIEWER_VIEWED_URL,
                           guid=guid,
                           theme=theme)

app.wsgi_app = ProxyFix(app.wsgi_app)
if __name__ == '__main__':
    from settings import DEBUG, PORT
    app.debug = DEBUG
    if not DEBUG:
        app.run(host='0.0.0.0', port=PORT)
    else:
        app.run(port=PORT)
