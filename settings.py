DEBUG = False
PORT = 5000
USE_NGINX = True

# The system expects the Movie and tv show folders to exist in a
# BASE_PATH folder. The path to that folder is defined below
BASE_PATH = '/path/to/base/folder'
APP_NAME = '/waiter'

LOG_PATH = '/path/to/log/folder'
LOG_FILE_NAME = 'waiterLog'

MEDIAVIEWER_GUID_URL = 'http://127.0.0.1/mediaviewer/api/downloadtoken/%(guid)s/'
MEDIAVIEWER_GUID_OFFSET_URL = 'http://127.0.0.1/mediaviewer/ajaxvideoprogress/%(guid)s/%(filename)s/'
MEDIAVIEWER_DOWNLOADCLICK_URL = 'http://127.0.0.1/mediaviewer/api/downloadclick/'
MEDIAVIEWER_VIEWED_URL = 'http://127.0.0.1/mediaviewer/ajaxsuperviewed/'
WAITER_VIEWED_URL = '/waiter/viewed/'
WAITER_OFFSET_URL = '/waiter/offset/'

MEDIAVIEWER_SUFFIX = 'mv-encoded'

WAITER_USERNAME = 'username'
WAITER_PASSWORD = 'password'
VERIFY_REQUESTS = True

try:
    from local_settings import *
except: # nosec
    pass
