import unittest
from waiter import (isAlfredEncoding,
                    updateDownloadClick,
                    )
from settings import (MEDIAVIEWER_SUFFIX,
                      MEDIAVIEWER_DOWNLOADCLICK_URL,
                      WAITER_USERNAME,
                      WAITER_PASSWORD,
                      VERIFY_REQUESTS,
                      )

import mock
from mock import call

class TestWaiterAlfredEncodingCheck(unittest.TestCase):
    def test_isAlfredEncoded_True(self):
        filename = 'somefile.%s.mp4' % MEDIAVIEWER_SUFFIX
        self.assertTrue(isAlfredEncoding(filename))

    def test_isAlfreadEncoding_False(self):
        filename = 'somefile.mp4'
        self.assertFalse(isAlfredEncoding(filename))

class TestWaiterUpdateDownloadClick(unittest.TestCase):
    @mock.patch('waiter.requests')
    def test_updateDownloadClick(self,
                                 mock_requests):
        userid = 123
        tokenid = 234
        filename = 'somefile.mp4'
        size = 456

        updateDownloadClick(userid,
                            tokenid,
                            filename,
                            size,
                            )

        self.assertEquals(call(MEDIAVIEWER_DOWNLOADCLICK_URL,
                               data=dict(userid=123,
                                         tokenid=234,
                                         filename='somefile.mp4',
                                         size=456,
                                         ),
                               auth=(WAITER_USERNAME, WAITER_PASSWORD),
                               verify=VERIFY_REQUESTS),
                        mock_requests.post.call_args)
