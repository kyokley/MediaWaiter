import os
from distutils.util import strtobool

DEBUG = strtobool(os.getenv('FLASK_DEBUG', 'false').lower())
HOST = '127.0.0.1'
PORT = 5000
USE_NGINX = True

MINIMUM_FILE_SIZE = 10000000

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
# Generate a secret key
# Borrowed from https://gist.github.com/ndarville/3452907
SECRET_FILE = os.path.join(REPO_DIR, 'secret.txt')
try:
    with open(SECRET_FILE, 'r') as secret_file:
        SECRET_KEY = secret_file.read().strip()
except (IOError, FileNotFoundError):
    try:
        import random
        import string
        allowable_chars = (string.ascii_letters +
                           string.digits +
                           '!@#$%^&*()-_=+')
        SECRET_KEY = ''.join([random.SystemRandom().choice(allowable_chars)
                              for _ in range(50)])
        with open(SECRET_FILE, 'w') as secret_file:
            secret_file.write(SECRET_KEY)
    except IOError as e:
        raise Exception(f'{e}\nPlease create a {SECRET_FILE} file with random characters to generate your secret key!')

# The system expects the Movie and tv show folders to exist in a
# BASE_PATH folder. The path to that folder is defined below
BASE_PATH = '/path/to/base/folder'
APP_NAME = '/waiter'

LOG_PATH = '/path/to/log/folder'
LOG_FILE_NAME = 'waiterLog'

EXTERNAL_MEDIAVIEWER_BASE_URL = MEDIAVIEWER_BASE_URL = 'http://127.0.0.1/mediaviewer'
MEDIAVIEWER_GUID_URL = MEDIAVIEWER_BASE_URL + '/api/downloadtoken/%(guid)s/'
MEDIAVIEWER_GUID_OFFSET_URL = MEDIAVIEWER_BASE_URL + '/ajaxvideoprogress/%(guid)s/%(filename)s/'
MEDIAVIEWER_VIEWED_URL = MEDIAVIEWER_BASE_URL + '/ajaxsuperviewed/'

WAITER_VIEWED_URL = '/waiter/viewed/'
WAITER_OFFSET_URL = '/waiter/offset/'

MEDIAVIEWER_SUFFIX = 'mv-encoded'

WAITER_USERNAME = 'username'
WAITER_PASSWORD = 'password'  # nosec
VERIFY_REQUESTS = True

GOOGLE_CAST_APP_ID = 'insert cast SDK ID here'
MEDIAWAITER_PROTOCOL = 'https://'

try:
    from local_settings import *
except: # nosec
    pass
