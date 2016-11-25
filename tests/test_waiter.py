import unittest
from waiter import (isAlfredEncoding,
                    updateDownloadClick,
                    getTokenByGUID,
                    get_dirPath,
                    buildMovieEntries,
                    _buildFileDictHelper,
                    send_file_for_download,
                    get_file,
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

class TestBuildMovieEntries(unittest.TestCase):
    def setUp(self):
        self.os_patcher = mock.patch('waiter.os')
        self.mock_os = self.os_patcher.start()
        self._buildFileDictHelper_patcher = mock.patch('waiter._buildFileDictHelper')
        self.mock_buildFileDictHelper = self._buildFileDictHelper_patcher.start()
        self.BASE_PATH_patcher = mock.patch('waiter.BASE_PATH', '/base/path')
        self.BASE_PATH_patcher.start()

        self.mock_os.path.join.side_effect = ['path/to/movie',
                                              '/base/path/to/movie']
        self.mock_os.walk.return_value = [('/root/path', [], ['file1',
                                                              'file2',
                                                              'file3'])]

        self.token = {'path': 'a/movie/path',
                      'filename': 'test_movie_name'}


    def tearDown(self):
        self.os_patcher.stop()
        self._buildFileDictHelper_patcher.stop()
        self.BASE_PATH_patcher.stop()

    def test_all_valid_files(self):
        expected = [self.mock_buildFileDictHelper.return_value,
                    self.mock_buildFileDictHelper.return_value,
                    self.mock_buildFileDictHelper.return_value]
        actual = buildMovieEntries(self.token)
        self.assertEqual(expected, actual)

        self.mock_buildFileDictHelper.assert_any_call('/root/path', 'file1', self.token)
        self.mock_buildFileDictHelper.assert_any_call('/root/path', 'file2', self.token)
        self.mock_buildFileDictHelper.assert_any_call('/root/path', 'file3', self.token)

    def test_no_valid_files(self):
        self.mock_buildFileDictHelper.return_value = None

        expected = []
        actual = buildMovieEntries(self.token)
        self.assertEqual(expected, actual)

        self.mock_buildFileDictHelper.assert_any_call('/root/path', 'file1', self.token)
        self.mock_buildFileDictHelper.assert_any_call('/root/path', 'file2', self.token)
        self.mock_buildFileDictHelper.assert_any_call('/root/path', 'file3', self.token)

class TestBuildFileDictHelper(unittest.TestCase):
    def setUp(self):
        self.getsize_patcher = mock.patch('waiter.os.path.getsize')
        self.mock_getsize = self.getsize_patcher.start()

        self.MINIMUM_FILE_SIZE_patcher = mock.patch('waiter.MINIMUM_FILE_SIZE', 10000000)
        self.MINIMUM_FILE_SIZE_patcher.start()
        self.STREAMABLE_FILE_TYPES_patcher = mock.patch('waiter.STREAMABLE_FILE_TYPES', '.mp4')
        self.STREAMABLE_FILE_TYPES_patcher.start()
        self.isAlfredEncoding_patcher = mock.patch('waiter.isAlfredEncoding')
        self.mock_isAlfredEncoding = self.isAlfredEncoding_patcher.start()
        self.hashed_filename_patcher = mock.patch('waiter.hashed_filename')
        self.mock_hashed_filename = self.hashed_filename_patcher.start()
        self.buildWaiterPath_patcher = mock.patch('waiter.buildWaiterPath')
        self.mock_buildWaiterPath = self.buildWaiterPath_patcher.start()
        self.humansize_patcher = mock.patch('waiter.humansize')
        self.mock_humansize = self.humansize_patcher.start()

        self.token = {'filename': 'some.dir',
                      'guid': 'asdf1234'}

    def tearDown(self):
        self.getsize_patcher.stop()
        self.MINIMUM_FILE_SIZE_patcher.stop()
        self.STREAMABLE_FILE_TYPES_patcher.stop()
        self.isAlfredEncoding_patcher.stop()
        self.humansize_patcher.stop()
        self.hashed_filename_patcher.stop()
        self.buildWaiterPath_patcher.stop()

    def test_file_too_small(self):
        self.mock_getsize.return_value = 1000000

        expected = None
        actual = _buildFileDictHelper('root', 'filename.mp4', self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with('root/filename.mp4')
        self.assertFalse(self.mock_buildWaiterPath.called)
        self.assertFalse(self.mock_hashed_filename.called)
        self.assertFalse(self.mock_isAlfredEncoding.called)

    def test_file_not_streamable(self):
        self.mock_getsize.return_value = 100000000

        expected = None
        actual = _buildFileDictHelper('root', 'filename.mkv', self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with('root/filename.mkv')
        self.assertFalse(self.mock_buildWaiterPath.called)
        self.assertFalse(self.mock_hashed_filename.called)
        self.assertFalse(self.mock_isAlfredEncoding.called)

    def test_is_not_encoded(self):
        self.mock_getsize.return_value = 100000000
        self.mock_isAlfredEncoding.return_value = False

        expected = None
        actual = _buildFileDictHelper('root', 'filename.mp4', self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with('root/filename.mp4')
        self.assertFalse(self.mock_buildWaiterPath.called)
        self.assertFalse(self.mock_hashed_filename.called)
        self.mock_isAlfredEncoding.assert_called_once_with('filename.mp4')

    def test_valid_file(self):
        self.mock_getsize.return_value = 100000000

        expected = {'path': self.mock_buildWaiterPath.return_value,
                    'streamingPath': self.mock_buildWaiterPath.return_value,
                    'waiterPath': 'some.dir/filename.mp4',
                    'unhashedPath': 'root/filename.mp4',
                    'streamable': True,
                    'filename': 'filename.mp4',
                    'size': self.mock_humansize.return_value,
                    'isAlfredEncoding': True,
                    'ismovie': True}
        actual = _buildFileDictHelper('root', 'filename.mp4', self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with('root/filename.mp4')
        self.mock_buildWaiterPath.assert_any_call('stream',
                                                  'asdf1234',
                                                  self.mock_hashed_filename.return_value,
                                                  includeLastSlash=True)
        self.mock_buildWaiterPath.assert_any_call('file',
                                                  'asdf1234',
                                                  self.mock_hashed_filename.return_value,
                                                  includeLastSlash=True)
        self.mock_isAlfredEncoding.assert_called_once_with('filename.mp4')

class TestSendFileForDownload(unittest.TestCase):
    def setUp(self):
        self.BASE_PATH_patcher = mock.patch('waiter.BASE_PATH', 'BASE_PATH')
        self.BASE_PATH_patcher.start()
        self.getTokenByGUID_patcher = mock.patch('waiter.getTokenByGUID')
        self.mock_getTokenByGUID = self.getTokenByGUID_patcher.start()
        self.render_template_patcher = mock.patch('waiter.render_template')
        self.mock_render_template = self.render_template_patcher.start()
        self.checkForValidToken_patcher = mock.patch('waiter.checkForValidToken')
        self.mock_checkForValidToken = self.checkForValidToken_patcher.start()
        self.buildMovieEntries_patcher = mock.patch('waiter.buildMovieEntries')
        self.mock_buildMovieEntries = self.buildMovieEntries_patcher.start()
        self.hashed_filename_patcher = mock.patch('waiter.hashed_filename')
        self.mock_hashed_filename = self.hashed_filename_patcher.start()
        self.send_file_partial_patcher = mock.patch('waiter.send_file_partial')
        self.mock_send_file_partial = self.send_file_partial_patcher.start()

        self.token = {'path': 'test_path',
                      'filename': 'test_filename',
                      'ismovie': False,
                      }
        self.mock_getTokenByGUID.return_value = self.token
        self.mock_checkForValidToken.return_value = None
        self.mock_buildMovieEntries.return_value = [{'waiterPath': 'path/to/file',
                                                     'unhashedPath': 'unhashed/path/to/file',
                                                     }]
        self.mock_hashed_filename.return_value = 'hashPath'

    def tearDown(self):
        self.BASE_PATH_patcher.stop()
        self.getTokenByGUID_patcher.stop()
        self.render_template_patcher.stop()
        self.checkForValidToken_patcher.stop()
        self.buildMovieEntries_patcher.stop()
        self.hashed_filename_patcher.stop()
        self.send_file_partial_patcher.stop()

    def test_handle_exception(self):
        self.mock_checkForValidToken.side_effect = Exception('some error')
        expected = self.mock_render_template.return_value
        actual = send_file_for_download('guid', 'hashPath')
        self.assertEqual(expected, actual)
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='An error has occurred')

    def test_invalid_token(self):
        self.mock_checkForValidToken.return_value = 'got some error'

        expected = self.mock_render_template.return_value
        actual = send_file_for_download('guid', 'hashPath')
        self.assertEqual(expected, actual)
        self.mock_getTokenByGUID.assert_called_once_with('guid')
        self.mock_checkForValidToken.assert_called_once_with(self.token, 'guid')
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='got some error')

    def test_movie_file(self):
        self.token['ismovie'] = True

        expected = self.mock_send_file_partial.return_value
        actual = send_file_for_download('guid', 'hashPath')
        self.assertEqual(expected, actual)
        self.mock_buildMovieEntries.assert_called_once_with(self.token)
        self.mock_hashed_filename.assert_called_once_with('path/to/file')
        self.mock_send_file_partial.assert_called_once_with('BASE_PATH/test_path/test_filename/unhashed/path/to/file',
                                                            filename='file',
                                                            token=self.token)

    def test_bad_movie_file(self):
        self.token['ismovie'] = True

        expected = self.mock_render_template.return_value
        actual = send_file_for_download('guid', 'badHashPath')
        self.assertEqual(expected, actual)
        self.mock_buildMovieEntries.assert_called_once_with(self.token)
        self.mock_hashed_filename.assert_called_once_with('path/to/file')
        self.assertFalse(self.mock_send_file_partial.called)
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='An error has occurred')

    def test_tv_file(self):
        expected = self.mock_send_file_partial.return_value
        actual = send_file_for_download('guid', 'hashPath')
        self.assertEqual(expected, actual)
        self.assertFalse(self.mock_buildMovieEntries.called)
        self.assertFalse(self.mock_hashed_filename.called)
        self.mock_send_file_partial.assert_called_once_with('test_path/test_filename',
                                                            filename='test_filename',
                                                            token=self.token)

class TestGetFile(unittest.TestCase):
    def setUp(self):
        self.log_patcher = mock.patch('waiter.log')
        self.mock_log = self.log_patcher.start()
        self.STREAMABLE_FILE_TYPES_patcher = mock.patch('waiter.STREAMABLE_FILE_TYPES', ('.mp4',))
        self.STREAMABLE_FILE_TYPES_patcher.start()
        self.getTokenByGUID_patcher = mock.patch('waiter.getTokenByGUID')
        self.mock_getTokenByGUID = self.getTokenByGUID_patcher.start()
        self.checkForValidToken_patcher = mock.patch('waiter.checkForValidToken')
        self.mock_checkForValidToken = self.checkForValidToken_patcher.start()
        self.render_template_patcher = mock.patch('waiter.render_template')
        self.mock_render_template = self.render_template_patcher.start()
        self.buildWaiterPath_patcher = mock.patch('waiter.buildWaiterPath')
        self.mock_buildWaiterPath = self.buildWaiterPath_patcher.start()
        self.hashed_filename_patcher = mock.patch('waiter.hashed_filename')
        self.mock_hashed_filename = self.hashed_filename_patcher.start()
        self.exists_patcher = mock.patch('waiter.os.path.exists')
        self.mock_exists = self.exists_patcher.start()
        self.getsize_patcher = mock.patch('waiter.os.path.getsize')
        self.mock_getsize = self.getsize_patcher.start()
        self.humansize_patcher = mock.patch('waiter.humansize')
        self.mock_humansize = self.humansize_patcher.start()
        self.isAlfredEncoding_patcher = mock.patch('waiter.isAlfredEncoding')
        self.mock_isAlfredEncoding = self.isAlfredEncoding_patcher.start()

        self.token = {'ismovie': False,
                      'filename': 'test_filename.mp4',
                      'path': 'test/path',
                      'displayname': 'test_displayname',
                      'auto_download': 'test_auto_download',
                      }
        self.mock_getTokenByGUID.return_value = self.token
        self.mock_checkForValidToken.return_value = None
        self.mock_hashed_filename.return_value = 'test_hash'

    def tearDown(self):
        self.log_patcher.stop()
        self.STREAMABLE_FILE_TYPES_patcher.stop()
        self.getTokenByGUID_patcher.stop()
        self.render_template_patcher.stop()
        self.checkForValidToken_patcher.stop()
        self.buildWaiterPath_patcher.stop()
        self.hashed_filename_patcher.stop()
        self.exists_patcher.stop()
        self.getsize_patcher.stop()
        self.humansize_patcher.stop()
        self.isAlfredEncoding_patcher.stop()

    def test_invalid_token(self):
        self.mock_checkForValidToken.return_value = 'got an error'

        expected = self.mock_render_template.return_value
        actual = get_file('guid')
        self.assertEqual(expected, actual)
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='got an error')

    def test_movie_file(self):
        self.token['ismovie'] = True

        expected = self.mock_render_template.return_value
        actual = get_file('guid')
        self.assertEqual(expected, actual)
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='Invalid URL for movie type')

    def test_file_does_not_exist(self):
        self.mock_exists.return_value = False

        expected = self.mock_render_template.return_value
        actual = get_file('guid')
        self.assertEqual(expected, actual)
        self.mock_render_template.assert_called_once_with('error.html',
                                                          title='Error',
                                                          errorText='An error has occurred')
        self.mock_exists.assert_called_once_with('test/path/test_filename.mp4')
        self.mock_log.error.assert_called_once_with('File test/path/test_filename.mp4 does not exists')
        self.assertFalse(self.mock_buildWaiterPath.called)

    def test_valid(self):
        expected_file_dict = {'path': self.mock_buildWaiterPath.return_value,
                              'streamingPath': self.mock_buildWaiterPath.return_value,
                              'streamable': True,
                              'unhashedPath': 'test/path/test_filename.mp4',
                              'size': self.mock_humansize.return_value,
                              'filename': 'test_filename.mp4',
                              'displayName': 'test_displayname',
                              'isAlfredEncoding': self.mock_isAlfredEncoding.return_value,
                              'ismovie': False}
        expected = self.mock_render_template.return_value
        actual = get_file('guid')
        self.assertEqual(expected, actual)
        self.mock_render_template.assert_called_once_with('display.html',
                                                          title='test_displayname',
                                                          files=[expected_file_dict],
                                                          auto_download='test_auto_download')
        self.mock_buildWaiterPath.assert_any_call('stream',
                                                  'guid',
                                                  'test_hash',
                                                  )
        self.mock_buildWaiterPath.assert_any_call('file',
                                                  'guid',
                                                  'test_hash',
                                                  )
