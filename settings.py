import os
from pathlib import Path
from distutils.util import strtobool

DEBUG = strtobool(os.getenv("FLASK_DEBUG", "false").lower())
HOST = "127.0.0.1"
PORT = 5000
USE_NGINX = strtobool(os.getenv("MW_USE_NGINX", "true").lower())

MINIMUM_FILE_SIZE = 20_000_000

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
# Generate a secret key
# Borrowed from https://gist.github.com/ndarville/3452907
SECRET_FILE = os.path.join(REPO_DIR, "secret.txt")
try:
    with open(SECRET_FILE, "r") as secret_file:
        SECRET_KEY = secret_file.read().strip()
except (IOError, FileNotFoundError):
    try:
        import random
        import string

        allowable_chars = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
        SECRET_KEY = "".join(
            [random.SystemRandom().choice(allowable_chars) for _ in range(50)]
        )
        with open(SECRET_FILE, "w") as secret_file:
            secret_file.write(SECRET_KEY)
    except IOError as e:
        raise Exception(
            f"{e}\nPlease create a {SECRET_FILE} file with random characters to generate your secret key!"
        )

# The system expects the Movie and tv show folders to exist in a
# BASE_PATH folder. The path to that folder is defined below
BASE_PATH = Path(os.getenv("MW_BASE_PATH")) if os.getenv("MW_BASE_PATH") else Path("/path/to/base/folder")

# Directories for server status checking. Should be relative to the BASE_PATH.
MEDIA_DIRS = ["Movies", "tv_shows"]

APP_NAME = "/waiter"

LOG_PATH = Path(os.getenv("MW_LOG_DIR")) if os.getenv("MW_LOG_DIR") else Path("/path/to/log/folder")
LOG_FILE_NAME = "waiterLog"

EXTERNAL_MEDIAVIEWER_BASE_URL = os.getenv('MW_EXTERNAL_MEDIAVIEWER_BASE_URL', 'http://localhost:8000/mediaviewer')
MEDIAVIEWER_BASE_URL = os.getenv('MW_MEDIAVIEWER_BASE_URL', 'http://mediaviewer:8000/mediaviewer')

MEDIAVIEWER_GUID_URL = MEDIAVIEWER_BASE_URL + "/api/downloadtoken/%(guid)s/"
MEDIAVIEWER_GUID_OFFSET_URL = (
    MEDIAVIEWER_BASE_URL + "/ajaxvideoprogress/%(guid)s/%(filename)s/"
)
MEDIAVIEWER_VIEWED_URL = MEDIAVIEWER_BASE_URL + "/ajaxsuperviewed/"

WAITER_VIEWED_URL = "/waiter/viewed/"
WAITER_OFFSET_URL = "/waiter/offset/"

MEDIAVIEWER_SUFFIX = os.getenv('MEDIAVIEWER_SUFFIX', 'mv-encoded')

WAITER_USERNAME = os.getenv('WAITER_USERNAME')
WAITER_PASSWORD = os.getenv('WAITER_PASSWORD')
VERIFY_REQUESTS = True

GOOGLE_CAST_APP_ID = "insert cast SDK ID here"
MEDIAWAITER_PROTOCOL = os.getenv('MW_MEDIAWAITER_PROTOCOL', "https://")

REQUESTS_TIMEOUT = 3  # in secs

DEFAULT_THEME = "dark"

JITSI_JWT_APP_ID = os.environ.get("JITSI_JWT_APP_ID", "")
JITSI_JWT_APP_SECRET = os.environ.get("JITSI_JWT_APP_SECRET", "")
JITSI_JWT_SUB = os.environ.get("JITSI_JWT_SUB", "")

try:
    from local_settings import *  # noqa
except:  # nosec # noqa
    pass
