import logging, os
from logging.handlers import RotatingFileHandler
from settings import LOG_FILE_NAME, LOG_PATH

fullLogPath = os.path.join(LOG_PATH, LOG_FILE_NAME)


class LogFile(object):
    logger = None

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(LogFile, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    @classmethod
    def getLogger(cls):
        if not cls.logger:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            log = logging.getLogger("waiter")
            log.setLevel(logging.DEBUG)
            rfh = RotatingFileHandler(
                fullLogPath,
                mode="a",
                maxBytes=1000000,
                backupCount=10,
            )
            rfh.setFormatter(formatter)
            log.addHandler(rfh)
            cls.logger = log

        return cls.logger


log = LogFile.getLogger()
