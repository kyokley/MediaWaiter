import time
import re
import requests

from werkzeug import url_fix
from functools import wraps
from log import log
from settings import (APP_NAME,
                      MEDIAVIEWER_GUID_OFFSET_URL,
                      WAITER_USERNAME,
                      WAITER_PASSWORD,
                      VERIFY_REQUESTS,
                      )
from flask import request, current_app

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
            for i in xrange(self.attempts):
                try:
                    log.debug('Attempt %s' % i)
                    res = func(*args, **kwargs)
                    log.debug('Success')
                    return res
                except Exception, e:
                    log.error(e)
                time.sleep(self.interval)
            else:
                raise Exception('Failure after %s attempts' % self.attempts)
        return wrap

def logErrorsAndContinue(func):
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        log.debug('logErrorsAndContinue')
        log.debug('Attempting %s' % func.__name__)
        try:
            res = func(*args, **kwargs)
            return res
        except Exception, e:
            log.error(e, exc_info=True)
            print e
            return 'An error has occurred'
    return func_wrapper

def checkForValidToken(token, guid):
    if not token:
        log.info('Token is invalid GUID: %s' % (guid,))
        return "This token is invalid! Return to the main site to generate a new one."
    if not token['isvalid']:
        log.info('Token Expired GUID: %s' % (guid,))
        return "This token has expired! Return to the main site to generate a new one."

def parseRangeHeaders(size, range_header):
    byte1, byte2 = 0, None

    if range_header:
        m = re.search('(\d+)-(\d*)', range_header)
        g = m.groups()

        byte1 = int(g[0]) if g[0] else 0
        byte2 = int(g[1]) if g[1] else None

    length = size - byte1
    if byte2 is not None:
        length = byte2 - byte1
    return (length, byte1, byte2)

def buildWaiterPath(place, guid, filePath, includeLastSlash=True):
    path = '%s/%s/%s%s%s' % (APP_NAME,
                             place,
                             guid,
                             includeLastSlash and '/' or '',
                             url_fix(filePath))
    return path

def getVideoOffset(filename, guid):
    try:
        resp = requests.get(MEDIAVIEWER_GUID_OFFSET_URL % {'guid': guid,
                                                           'filename': filename},
                            auth=(WAITER_USERNAME, WAITER_PASSWORD),
                            verify=VERIFY_REQUESTS,
                            )
        resp.raise_for_status()
        data = resp.json()
        offset = data['offset']
    except Exception, e:
        log.error(e)
        offset = 0
    return offset

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
    except Exception, e:
        log.error(e)

def deleteVideoOffset(filename, guid):
    try:
        resp = requests.delete(MEDIAVIEWER_GUID_OFFSET_URL % {'guid': guid,
                                                              'filename': filename},
                               auth=(WAITER_USERNAME, WAITER_PASSWORD),
                               verify=VERIFY_REQUESTS,
                               )
        resp.raise_for_status()
    except Exception, e:
        log.error(e)
