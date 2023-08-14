import unittest
import pytest
from pathlib import Path
from waiter import (
    isAlfredEncoding,
    getTokenByGUID,
    get_dirPath,
    buildEntries,
    _buildFileDictHelper,
    send_file_for_download,
    get_file,
    get_status,
    xsendfile,
    send_file_partial,
)
from settings import REQUESTS_TIMEOUT, DEFAULT_THEME
import mock


class TestIsAlfredEncoding:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        mocker.patch("waiter.MEDIAVIEWER_SUFFIX", "TEST_SUFFIX")

    def test_not_alfred_encoded(self):
        test_str = "test_str"
        actual = isAlfredEncoding(test_str)
        assert not actual

    def test_is_alfred_encoded(self):
        test_str = "test_str_TEST_SUFFIX"
        actual = isAlfredEncoding(test_str)
        assert actual


class TestGetTokenByGUID:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        mocker.patch("waiter.MEDIAVIEWER_GUID_URL", "TEST_GUID_URL%(guid)s")
        mocker.patch("waiter.WAITER_USERNAME", "TEST_WAITER_USERNAME")
        mocker.patch("waiter.WAITER_PASSWORD", "TEST_WAITER_PASSWORD")
        mocker.patch("waiter.VERIFY_REQUESTS", "TEST_VERIFY_REQUESTS")

        self.requests_patcher = mock.patch("waiter.requests")
        self.mock_requests = self.requests_patcher.start()
        self.mock_get_result = mock.MagicMock()
        self.mock_requests.get.return_value = self.mock_get_result

    def test_getTokenByGUID(self):
        test_guid = "_url"
        expected = self.mock_get_result.json.return_value
        actual = getTokenByGUID(test_guid)

        self.mock_requests.get.assert_called_once_with(
            "TEST_GUID_URL_url",
            auth=("TEST_WAITER_USERNAME", "TEST_WAITER_PASSWORD"),
            verify="TEST_VERIFY_REQUESTS",
            timeout=REQUESTS_TIMEOUT,
        )
        self.mock_get_result.json.assert_called_once_with()
        assert expected == actual


class TestGetDirPath:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        mocker.patch("waiter.EXTERNAL_MEDIAVIEWER_BASE_URL", "BASE_URL")
        mocker.patch("waiter.WAITER_OFFSET_URL", "OFFSET_URL")
        self.mock_getTokenByGUID = mocker.patch("waiter.getTokenByGUID")
        self.mock_render_template = mocker.patch("waiter.render_template")
        self.mock_buildEntries = mocker.patch("waiter.buildEntries")
        self.mock_buildEntries.return_value = [
            {
                "filename": "qwe",
            },
            {
                "filename": "asd",
            },
            {
                "filename": "zxc",
            },
        ]
        self.mock_getMediaGenres = mocker.patch("waiter.getMediaGenres")
        self.mock_getMediaGenres.return_value = ("tv_genres", "movie_genres")

        self.mock_buildWaiterPath = mocker.patch("waiter.buildWaiterPath")

        self.mock_checkForValidToken = mocker.patch("waiter.checkForValidToken")
        self.test_guid = "test_guid"

    def test_getTokenByGUID_raises_exception(self):
        self.mock_getTokenByGUID.side_effect = Exception("Fake Error")

        expected = (self.mock_render_template.return_value, 400)
        actual = get_dirPath(self.test_guid)

        assert expected == actual
        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="An error has occurred",
            username=None,
            mediaviewer_base_url="BASE_URL",
            theme=DEFAULT_THEME,
        )

    def test_invalidToken(self):
        self.mock_checkForValidToken.return_value = "Got an error"

        expected = self.mock_render_template.return_value
        actual = get_dirPath(self.test_guid)

        assert expected == actual
        self.mock_checkForValidToken.assert_called_once_with(
            self.mock_getTokenByGUID.return_value, self.test_guid
        )
        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="Got an error",
            mediaviewer_base_url="BASE_URL",
            theme=mock.ANY,
        )

    def test_ismovie(self):
        self.mock_checkForValidToken.return_value = ""
        self.mock_getTokenByGUID.return_value = {
            "ismovie": True,
            "displayname": "test_display_name",
            "username": "some.user",
            "pathid": 123,
            "pathname": "test_pathname",
        }

        expected = self.mock_render_template.return_value
        actual = get_dirPath(self.test_guid)

        assert expected == actual
        self.mock_checkForValidToken.assert_called_once_with(
            self.mock_getTokenByGUID.return_value, self.test_guid
        )
        self.mock_getMediaGenres.assert_called_once_with(self.test_guid)
        self.mock_render_template.assert_called_once_with(
            "display.html",
            title="test_display_name",
            files=[{"filename": "asd"}, {"filename": "qwe"}, {"filename": "zxc"}],
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            ismovie=True,
            pathid=123,
            pathname="test_pathname",
            guid="test_guid",
            offsetUrl="OFFSET_URL",
            next_link=None,
            previous_link=None,
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            binge_mode=False,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
        )

    def test_not_a_movie(self):
        self.mock_checkForValidToken.return_value = ""
        self.mock_getTokenByGUID.return_value = {
            "ismovie": False,
            "displayname": "test_display_name",
            "filename": "test_filename",
            "path": "test_path",
            "username": "some.user",
            "pathid": 123,
            "pathname": "test_pathname",
        }

        expected = self.mock_render_template.return_value, 400
        actual = get_dirPath(self.test_guid)

        assert expected == actual

        self.mock_checkForValidToken.assert_called_once_with(
            self.mock_getTokenByGUID.return_value, self.test_guid
        )
        assert not self.mock_getMediaGenres.called
        assert not self.mock_buildWaiterPath.called

        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="An error has occurred",
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            theme=DEFAULT_THEME,
        )


class TestBuildMovieEntries:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        self.mock_os = mocker.patch("waiter.os")
        self.mock_buildFileDictHelper = mocker.patch("waiter._buildFileDictHelper")
        mocker.patch("waiter.BASE_PATH", "/base/path")

        self.mock_os.path.join.side_effect = ["path/to/movie", "/base/path/to/movie"]
        self.mock_os.walk.return_value = [
            ("/root/path", [], ["file1", "file2", "file3"])
        ]

        self.token = {
            "path": "a/movie/path",
            "filename": "test_movie_name",
            "ismovie": True,
        }

    def test_all_valid_files(self):
        expected = [
            self.mock_buildFileDictHelper.return_value,
            self.mock_buildFileDictHelper.return_value,
            self.mock_buildFileDictHelper.return_value,
        ]
        actual = buildEntries(self.token)
        assert expected == actual

        self.mock_buildFileDictHelper.assert_any_call(
            Path("/root/path"), "file1", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("/root/path"), "file2", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("/root/path"), "file3", self.token
        )

    def test_no_valid_files(self):
        self.mock_buildFileDictHelper.return_value = None

        expected = []
        actual = buildEntries(self.token)
        assert expected == actual

        self.mock_buildFileDictHelper.assert_any_call(
            Path("/root/path"), "file1", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("/root/path"), "file2", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("/root/path"), "file3", self.token
        )


class TestBuildFileDictHelper:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        self.mock_getsize = mocker.patch("waiter.os.path.getsize")

        mocker.patch("waiter.MINIMUM_FILE_SIZE", 10000000)
        mocker.patch("waiter.STREAMABLE_FILE_TYPES", ".mp4")
        self.mock_isAlfredEncoding = mocker.patch("waiter.isAlfredEncoding")
        self.mock_hashed_filename = mocker.patch("waiter.hashed_filename")
        self.mock_buildWaiterPath = mocker.patch("waiter.buildWaiterPath")
        self.mock_humansize = mocker.patch("waiter.humansize")

        self.token = {
            "filename": "some.dir",
            "guid": "asdf1234",
            "ismovie": True,
            "displayname": "Some Dir",
            "videoprogresses": [],
        }

    def test_file_too_small(self):
        self.mock_getsize.return_value = 1000000

        expected = None
        actual = _buildFileDictHelper("/root", "filename.mp4", self.token)
        assert expected == actual
        assert not self.mock_buildWaiterPath.called
        assert not self.mock_hashed_filename.called
        assert not self.mock_isAlfredEncoding.called

    def test_file_not_streamable(self):
        self.mock_getsize.return_value = 100000000

        expected = None
        actual = _buildFileDictHelper("/root", "filename.mkv", self.token)
        assert expected == actual
        assert not self.mock_buildWaiterPath.called
        assert not self.mock_hashed_filename.called
        assert not self.mock_isAlfredEncoding.called


class TestSendFileForDownload:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        mocker.patch("waiter.EXTERNAL_MEDIAVIEWER_BASE_URL", "BASE_URL")
        mocker.patch("waiter.BASE_PATH", "BASE_PATH")
        self.mock_getTokenByGUID = mocker.patch("waiter.getTokenByGUID")
        self.mock_render_template = mocker.patch("waiter.render_template")
        self.mock_checkForValidToken = mocker.patch("waiter.checkForValidToken")
        self.mock_buildEntries = mocker.patch("waiter.buildEntries")
        self.mock_hashed_filename = mocker.patch("waiter.hashed_filename")
        self.mock_send_file_partial = mocker.patch("waiter.send_file_partial")

        self.token = {
            "path": "test_path",
            "filename": "test_filename",
            "ismovie": False,
        }
        self.mock_getTokenByGUID.return_value = self.token
        self.mock_checkForValidToken.return_value = None
        self.mock_buildEntries.return_value = [
            {
                "hashedWaiterPath": "hashPath",
                "unhashedPath": Path("unhashed/path/to/file"),
            }
        ]
        self.mock_hashed_filename.return_value = "hashPath"

    def test_handle_exception(self):
        self.mock_checkForValidToken.side_effect = Exception("some error")
        expected = self.mock_render_template.return_value, 400
        actual = send_file_for_download("guid", "hashPath")
        assert expected == actual
        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="An error has occurred",
            mediaviewer_base_url="BASE_URL",
            username=None,
            theme=DEFAULT_THEME,
        )

    def test_invalid_token(self):
        self.mock_checkForValidToken.return_value = "got some error"

        expected = self.mock_render_template.return_value
        actual = send_file_for_download("guid", "hashPath")
        assert expected == actual
        self.mock_getTokenByGUID.assert_called_once_with("guid")
        self.mock_checkForValidToken.assert_called_once_with(self.token, "guid")
        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="got some error",
            mediaviewer_base_url="BASE_URL",
            theme=DEFAULT_THEME,
        )

    def test_movie_file(self):
        self.token["ismovie"] = True

        expected = self.mock_send_file_partial.return_value
        actual = send_file_for_download("guid", "hashPath")
        assert expected == actual
        self.mock_buildEntries.assert_called_once_with(self.token)
        assert not self.mock_hashed_filename.called
        self.mock_send_file_partial.assert_called_once_with(
            Path("unhashed/path/to/file"), "file", self.token
        )

    def test_bad_movie_file(self):
        self.token["ismovie"] = True

        expected = self.mock_render_template.return_value, 400
        actual = send_file_for_download("guid", "badHashPath")
        assert expected == actual
        self.mock_buildEntries.assert_called_once_with(self.token)
        assert not self.mock_hashed_filename.called
        assert not self.mock_send_file_partial.called
        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="An error has occurred",
            mediaviewer_base_url="BASE_URL",
            username=None,
            theme=DEFAULT_THEME,
        )

    def test_tv_file(self):
        expected = self.mock_send_file_partial.return_value
        actual = send_file_for_download("guid", "hashPath")
        assert expected == actual
        assert self.mock_buildEntries.called
        assert not self.mock_hashed_filename.called
        self.mock_send_file_partial.assert_called_once_with(
            Path("unhashed/path/to/file"), "file", self.token
        )


class TestGetFile:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        self.EXTERNAL_MEDIAVIEWER_BASE_URL_patcher = mocker.patch(
            "waiter.EXTERNAL_MEDIAVIEWER_BASE_URL", "BASE_URL"
        )
        self.WAITER_OFFSET_URL = mocker.patch("waiter.WAITER_OFFSET_URL", "OFFSET_URL")
        self.mock_log = mocker.patch("waiter.log")
        self.STREAMABLE_FILE_TYPES_patcher = mocker.patch(
            "waiter.STREAMABLE_FILE_TYPES", (".mp4",)
        )
        self.mock_getTokenByGUID = mocker.patch("waiter.getTokenByGUID")
        self.mock_checkForValidToken = mocker.patch("waiter.checkForValidToken")
        self.mock_render_template = mocker.patch("waiter.render_template")
        self.mock_buildWaiterPath = mocker.patch("waiter.buildWaiterPath")
        self.mock_hashed_filename = mocker.patch("waiter.hashed_filename")
        self.mock_getsize = mocker.patch("waiter.os.path.getsize")
        self.mock_humansize = mocker.patch("waiter.humansize")
        self.mock_isAlfredEncoding = mocker.patch("waiter.isAlfredEncoding")
        self.mock_buildEntries = mocker.patch("waiter.buildEntries")

        self.mock_getMediaGenres = mocker.patch("waiter.getMediaGenres")
        self.mock_getMediaGenres.return_value = ("tv_genres", "movie_genres")

        self.token = {
            "ismovie": False,
            "filename": "test_filename.mp4",
            "path": "test/path",
            "displayname": "test_displayname",
            "pathid": 123,
            "pathname": "test_pathname",
            "username": "some.user",
            "binge_mode": True,
        }
        self.mock_getTokenByGUID.return_value = self.token
        self.mock_checkForValidToken.return_value = None
        self.mock_hashed_filename.return_value = "test_hash"

    def test_invalid_token(self):
        self.mock_checkForValidToken.return_value = "got an error"

        expected = self.mock_render_template.return_value
        actual = get_file("guid")
        assert expected == actual
        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="got an error",
            mediaviewer_base_url="BASE_URL",
            theme=DEFAULT_THEME,
        )

    def test_movie_file(self):
        self.token["ismovie"] = True

        expected = self.mock_render_template.return_value
        actual = get_file("guid")
        assert expected == actual
        self.mock_render_template.assert_called_once_with(
            "error.html",
            title="Error",
            errorText="Invalid URL for movie type",
            mediaviewer_base_url="BASE_URL",
            theme=DEFAULT_THEME,
        )

    def test_valid(self):
        expected = self.mock_render_template.return_value
        actual = get_file("guid")
        assert expected == actual
        self.mock_getMediaGenres.assert_called_once_with("guid")
        self.mock_render_template.assert_called_once_with(
            "display.html",
            title="test_displayname",
            files=self.mock_buildEntries.return_value,
            ismovie=False,
            pathid=123,
            pathname="test_pathname",
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            guid="guid",
            offsetUrl="OFFSET_URL",
            next_link=None,
            previous_link=None,
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            binge_mode=True,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
        )

    def test_valid_with_next_and_previous(self):
        self.token["next_id"] = 123
        self.token["previous_id"] = 234

        expected = self.mock_render_template.return_value
        actual = get_file("guid")
        assert expected == actual
        self.mock_getMediaGenres.assert_called_once_with("guid")
        self.mock_render_template.assert_called_once_with(
            "display.html",
            title="test_displayname",
            files=self.mock_buildEntries.return_value,
            ismovie=False,
            pathid=123,
            pathname="test_pathname",
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            guid="guid",
            offsetUrl="OFFSET_URL",
            next_link="BASE_URL/downloadlink/123/",
            previous_link="BASE_URL/downloadlink/234/",
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            binge_mode=True,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
        )

    def test_valid_no_binge_mode(self):
        self.token["binge_mode"] = False

        expected = self.mock_render_template.return_value
        actual = get_file("guid")
        assert expected == actual
        self.mock_getMediaGenres.assert_called_once_with("guid")
        self.mock_render_template.assert_called_once_with(
            "display.html",
            title="test_displayname",
            files=self.mock_buildEntries.return_value,
            ismovie=False,
            pathid=123,
            pathname="test_pathname",
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            guid="guid",
            offsetUrl="OFFSET_URL",
            next_link=None,
            previous_link=None,
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            binge_mode=False,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
        )


class TestGetStatus:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        mocker.patch("waiter.BASE_PATH", "BASE_PATH")
        self.mock_exists = mocker.patch("waiter.os.path.exists")
        self.mock_log = mocker.patch("waiter.log")
        self.mock_jsonify = mocker.patch("waiter.jsonify")

    def test_bad_tv_status(self):
        self.mock_exists.side_effect = [True, False]

        expected = ({"status": False}, 500)
        actual = get_status()
        assert expected == actual
        self.mock_log.debug.assert_any_call("Movies directory is good")
        self.mock_log.debug.assert_any_call("tv shows directory failed")
        self.mock_log.debug.assert_any_call("status: False")

    def test_bad_movie_status(self):
        self.mock_exists.side_effect = [False, True]

        expected = ({"status": False}, 500)
        actual = get_status()
        assert expected == actual
        self.mock_log.debug.assert_any_call("tv shows directory is good")
        self.mock_log.debug.assert_any_call("Movies directory failed")
        self.mock_log.debug.assert_any_call("status: False")

    def test_bad_bad_status(self):
        self.mock_exists.side_effect = [False, False]

        expected = ({"status": False}, 500)
        actual = get_status()
        assert expected == actual
        self.mock_log.debug.assert_any_call("tv shows directory failed")
        self.mock_log.debug.assert_any_call("Movies directory failed")
        self.mock_log.debug.assert_any_call("status: False")

    def test_good_status(self):
        self.mock_exists.side_effect = [True, True]

        expected = ({"status": True}, 200)
        actual = get_status()
        assert expected == actual
        self.mock_log.debug.assert_any_call("tv shows directory is good")
        self.mock_log.debug.assert_any_call("Movies directory is good")
        self.mock_log.debug.assert_any_call("status: True")


class TestXSendfile:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        self.mock_log = mocker.patch("waiter.log")
        self.mock_mimetypes = mocker.patch("waiter.mimetypes")
        self.mock_response = mocker.patch("waiter.Response")

        self.response_obj = mock.MagicMock()

        self.mock_response.return_value = self.response_obj

    def test_(self):
        path = "path/to/file"
        filename = "test_filename.mp4"
        size = 100

        expected = self.response_obj
        actual = xsendfile(path, filename, size)
        assert expected == actual


# I wasn't able to convert this test because mocking waiter.request was
# failing some werkzeug thing. *shrugs*
class TestSendFilePartialWithNginx(unittest.TestCase):
    def setUp(self):
        self.USE_NGINX_patcher = mock.patch("waiter.USE_NGINX", True)
        self.USE_NGINX_patcher.start()
        self.request_patcher = mock.patch("waiter.request")
        self.mock_request = self.request_patcher.start()
        self.getsize_patcher = mock.patch("waiter.os.path.getsize")
        self.mock_getsize = self.getsize_patcher.start()
        self.parseRangeHeaders_patcher = mock.patch("waiter.parseRangeHeaders")
        self.mock_parseRangeHeaders = self.parseRangeHeaders_patcher.start()
        self.xsendfile_patcher = mock.patch("waiter.xsendfile")
        self.mock_xsendfile = self.xsendfile_patcher.start()
        self.app_sendfile_patcher = mock.patch("waiter.app_sendfile")
        self.mock_app_sendfile = self.app_sendfile_patcher.start()

        self.mock_request.headers.get.return_value = "test_range_header"

        self.path = "path/to/file"
        self.filename = "test_filename.mp4"
        self.token = {"userid": 123, "tokenid": 234}
        self.mock_getsize.return_value = 100
        self.mock_parseRangeHeaders.return_value = (100, 0, 100)

    def tearDown(self):
        self.USE_NGINX_patcher.stop()
        self.request_patcher.stop()
        self.getsize_patcher.stop()
        self.parseRangeHeaders_patcher.stop()
        self.xsendfile_patcher.stop()
        self.app_sendfile_patcher.stop()

    def test_with_range_header(self):
        expected = self.mock_xsendfile.return_value
        actual = send_file_partial(self.path, self.filename, self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with("path/to/file")
        self.assertFalse(self.mock_parseRangeHeaders.called)
        self.mock_xsendfile.assert_called_once_with(
            self.path, self.filename, 100, range_header="test_range_header"
        )
        self.assertFalse(self.mock_app_sendfile.called)

    def test_no_range_header(self):
        self.mock_request.headers.get.return_value = None

        expected = self.mock_xsendfile.return_value
        actual = send_file_partial(self.path, self.filename, self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with("path/to/file")
        self.assertFalse(self.mock_parseRangeHeaders.called)
        self.mock_xsendfile.assert_called_once_with(
            self.path, self.filename, 100, range_header=None
        )
        self.assertFalse(self.mock_app_sendfile.called)

    def test_test(self):
        expected = self.mock_xsendfile.return_value
        actual = send_file_partial(self.path, self.filename, self.token, test=True)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with("path/to/file")
        self.assertFalse(self.mock_parseRangeHeaders.called)
        self.mock_xsendfile.assert_called_once_with(
            self.path, self.filename, 100, range_header="test_range_header"
        )
        self.assertFalse(self.mock_app_sendfile.called)


class TestSendFilePartialWithoutNginx(unittest.TestCase):
    def setUp(self):
        self.USE_NGINX_patcher = mock.patch("waiter.USE_NGINX", False)
        self.USE_NGINX_patcher.start()
        self.request_patcher = mock.patch("waiter.request")
        self.mock_request = self.request_patcher.start()
        self.getsize_patcher = mock.patch("waiter.os.path.getsize")
        self.mock_getsize = self.getsize_patcher.start()
        self.parseRangeHeaders_patcher = mock.patch("waiter.parseRangeHeaders")
        self.mock_parseRangeHeaders = self.parseRangeHeaders_patcher.start()
        self.xsendfile_patcher = mock.patch("waiter.xsendfile")
        self.mock_xsendfile = self.xsendfile_patcher.start()
        self.app_sendfile_patcher = mock.patch("waiter.app_sendfile")
        self.mock_app_sendfile = self.app_sendfile_patcher.start()

        self.mock_request.headers.get.return_value = "test_range_header"

        self.path = "path/to/file"
        self.filename = "test_filename.mp4"
        self.token = {"userid": 123, "tokenid": 234}
        self.mock_getsize.return_value = 100
        self.mock_parseRangeHeaders.return_value = (100, 0, 100)

    def tearDown(self):
        self.USE_NGINX_patcher.stop()
        self.request_patcher.stop()
        self.getsize_patcher.stop()
        self.parseRangeHeaders_patcher.stop()
        self.xsendfile_patcher.stop()
        self.app_sendfile_patcher.stop()

    def test_with_range_header(self):
        expected = self.mock_app_sendfile.return_value
        actual = send_file_partial(self.path, self.filename, self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with("path/to/file")
        self.assertFalse(self.mock_parseRangeHeaders.called)
        self.mock_app_sendfile.assert_called_once_with(
            self.path, self.filename, 100, range_header="test_range_header"
        )
        self.assertFalse(self.mock_xsendfile.called)

    def test_no_range_header(self):
        self.mock_request.headers.get.return_value = None

        expected = self.mock_app_sendfile.return_value
        actual = send_file_partial(self.path, self.filename, self.token)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with("path/to/file")
        self.assertFalse(self.mock_parseRangeHeaders.called)
        self.mock_app_sendfile.assert_called_once_with(
            self.path, self.filename, 100, range_header=None
        )
        self.assertFalse(self.mock_xsendfile.called)

    def test_test(self):
        expected = self.mock_app_sendfile.return_value
        actual = send_file_partial(self.path, self.filename, self.token, test=True)
        self.assertEqual(expected, actual)
        self.mock_getsize.assert_called_once_with("path/to/file")
        self.assertFalse(self.mock_parseRangeHeaders.called)
        self.mock_app_sendfile.assert_called_once_with(
            self.path, self.filename, 100, range_header="test_range_header"
        )
        self.assertFalse(self.mock_xsendfile.called)
