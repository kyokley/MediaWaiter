import unittest
from waiter import (isAlfredEncoding,
                    updateDownloadClick,
                    getTokenByGUID,
                    get_dirPath,
                    buildMovieEntries,
                    )
from settings import (MEDIAVIEWER_DOWNLOADCLICK_URL,
                      WAITER_USERNAME,
                      WAITER_PASSWORD,
                      VERIFY_REQUESTS,
                      )

import mock
from mock import call

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

class TestIsAlfredEncoding(unittest.TestCase):
    def setUp(self):
        self.MEDIAVIEWER_SUFFIX_patcher = mock.patch('waiter.MEDIAVIEWER_SUFFIX', 'TEST_SUFFIX')
        self.MEDIAVIEWER_SUFFIX_patcher.start()

    def tearDown(self):
        self.MEDIAVIEWER_SUFFIX_patcher.stop()

    def test_not_alfred_encoded(self):
        test_str = 'test_str'
        actual = isAlfredEncoding(test_str)
        self.assertFalse(actual)

    def test_is_alfred_encoded(self):
        test_str = 'test_str_TEST_SUFFIX'
        actual = isAlfredEncoding(test_str)
        self.assertTrue(actual)

class TestGetTokenByGUID(unittest.TestCase):
    def setUp(self):
        self.MEDIAVIEWER_GUID_URL_patcher = mock.patch('waiter.MEDIAVIEWER_GUID_URL', 'TEST_GUID_URL%(guid)s')
        self.WAITER_USERNAME_patcher = mock.patch('waiter.WAITER_USERNAME', 'TEST_WAITER_USERNAME')
        self.WAITER_PASSWORD_patcher = mock.patch('waiter.WAITER_PASSWORD', 'TEST_WAITER_PASSWORD')
        self.VERIFY_REQUESTS_patcher = mock.patch('waiter.VERIFY_REQUESTS', 'TEST_VERIFY_REQUESTS')
        self.MEDIAVIEWER_GUID_URL_patcher.start()
        self.WAITER_USERNAME_patcher.start()
        self.WAITER_PASSWORD_patcher.start()
        self.VERIFY_REQUESTS_patcher.start()

        self.requests_patcher = mock.patch('waiter.requests')
        self.mock_requests = self.requests_patcher.start()
        self.mock_get_result = mock.MagicMock()
        self.mock_requests.get.return_value = self.mock_get_result

    def tearDown(self):
        self.MEDIAVIEWER_GUID_URL_patcher.stop()
        self.WAITER_USERNAME_patcher.stop()
        self.WAITER_PASSWORD_patcher.stop()
        self.VERIFY_REQUESTS_patcher.stop()
        self.requests_patcher.stop()

    def test_(self):
        test_guid = '_url'
        expected = self.mock_get_result.json.return_value
        actual = getTokenByGUID(test_guid)

        self.mock_requests.get.assert_called_once_with('TEST_GUID_URL_url',
                                                     auth=('TEST_WAITER_USERNAME', 'TEST_WAITER_PASSWORD'),
                                                     verify='TEST_VERIFY_REQUESTS')
        self.mock_get_result.json.assert_called_once_with()
        self.assertEqual(expected, actual)

class TestGetDirPath(unittest.TestCase):
    def setUp(self):
        self.getTokenByGUID_patcher = mock.patch('waiter.getTokenByGUID')
        self.mock_getTokenByGUID = self.getTokenByGUID_patcher.start()
        self.render_template_patcher = mock.patch('waiter.render_template')
        self.mock_render_template = self.render_template_patcher.start()
        self.buildMovieEntries_patcher = mock.patch('waiter.buildMovieEntries')
        self.mock_buildMovieEntries = self.buildMovieEntries_patcher.start()
        self.mock_buildMovieEntries.return_value = ['qwe', 'asd', 'zxc']

        self.buildWaiterPath_patcher = mock.patch('waiter.buildWaiterPath')
        self.mock_buildWaiterPath = self.buildWaiterPath_patcher.start()

        self.checkForValidToken_patcher = mock.patch('waiter.checkForValidToken')
        self.mock_checkForValidToken = self.checkForValidToken_patcher.start()
        self.test_guid = 'test_guid'

    def tearDown(self):
        self.getTokenByGUID_patcher.stop()
        self.render_template_patcher.stop()
        self.checkForValidToken_patcher.stop()
        self.buildMovieEntries_patcher.stop()
        self.buildWaiterPath_patcher.stop()

    def test_getTokenByGUID_raises_exception(self):
        self.mock_getTokenByGUID.side_effect = Exception('Fake Error')

        expected = self.mock_render_template.return_value
        actual = get_dirPath(self.test_guid)

        self.assertEqual(expected, actual)
        self.mock_getTokenByGUID.assert_called_once_with(self.test_guid)
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='An error has occurred')

    def test_invalidToken(self):
        self.mock_checkForValidToken.return_value = 'Got an error'

        expected = self.mock_render_template.return_value
        actual = get_dirPath(self.test_guid)

        self.assertEqual(expected, actual)
        self.mock_checkForValidToken.assert_called_once_with(self.mock_getTokenByGUID.return_value,
                                                             self.test_guid)
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='Got an error')

    def test_ismovie(self):
        self.mock_checkForValidToken.return_value = ''
        self.mock_getTokenByGUID.return_value = {'ismovie': True,
                                                 'displayname': 'test_display_name',
                                                 }

        expected = self.mock_render_template.return_value
        actual = get_dirPath(self.test_guid)

        self.assertEqual(expected, actual)
        self.mock_checkForValidToken.assert_called_once_with(self.mock_getTokenByGUID.return_value,
                                                             self.test_guid)
        self.mock_render_template.assert_called_once_with('display.html',
                                                          title='test_display_name',
                                                          files=['asd', 'qwe', 'zxc'])

    def test_not_a_movie(self):
        self.mock_checkForValidToken.return_value = ''
        self.mock_getTokenByGUID.return_value = {'ismovie': False,
                                                 'displayname': 'test_display_name',
                                                 'filename': 'test_filename',
                                                 'path': 'test_path',
                                                 }

        expected = self.mock_render_template.return_value
        actual = get_dirPath(self.test_guid)

        self.assertEqual(expected, actual)
        self.mock_checkForValidToken.assert_called_once_with(self.mock_getTokenByGUID.return_value,
                                                             self.test_guid)
        self.mock_render_template.assert_called_once_with('display.html',
                                                          title='test_display_name',
                                                          files=[{'path': self.mock_buildWaiterPath.return_value,
                                                                  'filename': 'test_filename'}])

        self.mock_buildWaiterPath.assert_called_once_with('file',
                                                          self.test_guid,
                                                          'test_path')

