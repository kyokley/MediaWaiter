import time
import re
import requests

from werkzeug import url_fix
from log import log
from settings import (APP_NAME,
                      MEDIAVIEWER_BASE_URL,
                      MEDIAVIEWER_GUID_OFFSET_URL,
                      WAITER_USERNAME,
                      WAITER_PASSWORD,
                      VERIFY_REQUESTS,
                      SECRET_KEY,
                      MEDIAWAITER_PROTOCOL,
                      HOST,
                      PORT,
                      )
import hashlib

suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
def humansize(nbytes):
    if nbytes == 0: return '0 B'
    i = 0
    while nbytes >= 1024 and i < len(suffixes)-1:
        nbytes /= 1024.
        i += 1
    f = ('%.2f' % nbytes).rstrip('0').rstrip('.')
    return '%s %s' % (f, suffixes[i])

class delayedRetry(object):
    def __init__(self, attempts=5, interval=1):
        self.attempts = attempts
        self.interval = interval

    def __call__(self, func):
        def wrap(*args, **kwargs):
            log.debug('Attempting %s' % func.__name__)
            last_exc = None
            for i in range(self.attempts):
                try:
                    log.debug('Attempt %s' % i)
                    res = func(*args, **kwargs)
                    log.debug('Success')
                    return res
                except Exception as e:
                    log.error(e)
                    last_exc = e
                time.sleep(self.interval)
            else:
                log.error('Failure after %s attempts' % self.attempts)
                raise last_exc
        return wrap

def checkForValidToken(token, guid):
    if not token:
        log.warn('Token is invalid GUID: %s' % (guid,))
        return "This token is invalid! Return to Movie or TV Show tab to generate a new one."
    if not token['isvalid']:
        log.warn('Token Expired GUID: %s' % (guid,))
        return "This token has expired! Return to Movie or TV Show tab to generate a new one."

def parseRangeHeaders(size, range_header):
    byte1, byte2 = 0, None

    if range_header:
        m = re.search(r'(\d+)-(\d*)', range_header)
        g = m.groups()

        byte1 = int(g[0]) if g[0] else 0
        byte2 = int(g[1]) if g[1] else None

    length = size - byte1
    if byte2 is not None:
        length = byte2 - byte1
    return (length, byte1, byte2)

def buildWaiterPath(place, guid, filePath, includeLastSlash=True):
    path = '{protocol}{host}:{port}{app_name}/{place}/{guid}{maybe_slash}{file_path}'.format(
                             protocol=MEDIAWAITER_PROTOCOL,
                             host=HOST,
                             port=PORT,
                             app_name=APP_NAME,
                             place=place,
                             guid=guid,
                             maybe_slash=includeLastSlash and '/' or '',
                             file_path=url_fix(filePath))
    return path

def getVideoOffset(filename, guid):
    data = {'offset': 0,
            'date_edited': None}
    try:
        resp = requests.get(MEDIAVIEWER_GUID_OFFSET_URL % {'guid': guid,
                                                           'filename': filename},
                            auth=(WAITER_USERNAME, WAITER_PASSWORD),
                            verify=VERIFY_REQUESTS,
                            )
        resp.raise_for_status()
        resp = resp.json()
        data['offset'] = resp['offset']
        if 'date_edited' in resp:
            data['date_edited'] = resp['date_edited']
    except Exception as e:
        log.error(e)
        raise
    return data

def setVideoOffset(filename, guid, offset):
    data = {'offset': offset}
    try:
        resp = requests.post(MEDIAVIEWER_GUID_OFFSET_URL % {'guid': guid,
                                                            'filename': filename},
                             auth=(WAITER_USERNAME, WAITER_PASSWORD),
                             verify=VERIFY_REQUESTS,
                             data=data,
                             )
        resp.raise_for_status()
    except Exception as e:
        log.error(e)
        raise

def deleteVideoOffset(filename, guid):
    try:
        resp = requests.delete(MEDIAVIEWER_GUID_OFFSET_URL % {'guid': guid,
                                                              'filename': filename},
                               auth=(WAITER_USERNAME, WAITER_PASSWORD),
                               verify=VERIFY_REQUESTS,
                               )
        resp.raise_for_status()
    except Exception as e:
        log.error(e)
        raise

def getMediaGenres(guid):
    genre_url = MEDIAVIEWER_BASE_URL + '/ajaxgenres/{}/'.format(guid)

    try:
        resp = requests.get(genre_url)
        resp.raise_for_status()
    except Exception as e:
        log.error(e)
        raise

    data = resp.json()
    tv_genres = [(mg[1], MEDIAVIEWER_BASE_URL + '/tvshows/genre/{}/'.format(mg[0]))
                    for mg in data['tv_genres']]
    movie_genres = [(mg[1], MEDIAVIEWER_BASE_URL + '/movies/genre/{}/'.format(mg[0]))
                        for mg in data['movie_genres']]
    return tv_genres, movie_genres

def hashed_filename(filename):
    peppered_string = filename + SECRET_KEY
    return hashlib.sha256(peppered_string).hexdigest()
