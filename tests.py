import unittest
from waiter import (app,
                    isAlfredEncoding,
                    APP_NAME,
                    updateDownloadClick,
                    )
from utils import humansize
from flask import render_template
from settings import MEDIAVIEWER_SUFFIX

import mock
from mock import call

#@app.route(APP_NAME + '/test2/')
#def get_test2():
    #fileDict = {'path': 'some/path/',
                #'filename': 'a filename',
                #'size': humansize(100000),
                #'isAlfredEncoding': isAlfredEncoding('a filename')}
    #files = [fileDict]
    #return render_template("display.html",
                           #title='testpage',
                           #files=files)

class TestWaiterAlfredEncodingCheck(unittest.TestCase):
    def test_isAlfredEncoded_True(self):
        filename = 'somefile.%s.mp4' % MEDIAVIEWER_SUFFIX
        self.assertTrue(isAlfredEncoding(filename))

    def test_isAlfreadEncoding_False(self):
        filename = 'somefile.mp4'
        self.assertFalse(isAlfredEncoding(filename))

class TestWaiterUpdateDownloadClick(unittest.TestCase):
    @mock.patch('waiter.urllib2.Request')
    @mock.patch('waiter.base64.encodestring')
    @mock.patch('waiter.urllib.urlencode')
    def test_updateDownloadClick(self,
                                 mock_urlencode,
                                 mock_base64encodestring,
                                 mock_Request):
        userid = 123
        tokenid = 234
        filename = 'somefile.mp4'
        size = 456

        base64encodedString = 'base64 encoded string'
        urlencodeSentinel = object()
        mock_requestObj = mock.MagicMock()

        mock_urlencode.return_value = urlencodeSentinel
        mock_base64encodestring.return_value = base64encodedString
        mock_Request.return_value = mock_requestObj

        updateDownloadClick(userid,
                            tokenid,
                            filename,
                            size,
                            )

        self.assertEquals(call(dict(userid=123,
                                    tokenid=234,
                                    filename='somefile.mp4',
                                    size=456,
                                    )),
                          mock_urlencode.call_args)
