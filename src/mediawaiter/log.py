import logging

from .settings import LOG_FILE_NAME, LOG_PATH

fullLogPath = LOG_PATH / LOG_FILE_NAME


class LogFile:
    logger = None

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    @classmethod
    def getLogger(cls):
        if not cls.logger:
            log = logging.getLogger("waiter")
            log.setLevel(logging.DEBUG)
            cls.logger = log

        return cls.logger


def logger():
    log = LogFile.getLogger()
    return log
