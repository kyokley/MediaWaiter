import pytest
from pathlib import Path
from waiter import (
    isAlfredEncoding,
    getTokenByGUID,
    get_dirPath,
    buildEntries,
    _buildFileDictHelper,
    _buildS3FileDict,
    is_s3_token,
    send_file_for_download,
    get_file,
    get_status,
    Subtitle,
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

        self.mock_get_collections = mocker.patch("waiter.get_collections")
        self.mock_get_collections.return_value = ((1, "Test Name"),)

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
            "tv_id": None,
            "tv_name": None,
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
            guid="test_guid",
            offsetUrl="OFFSET_URL",
            next_link=None,
            previous_link=None,
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            collections=((1, "Test Name"),),
            binge_mode=False,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
            tv_id=None,
            tv_name=None,
            is_mcp=False,
            og_title="",
            og_type="",
            og_url="",
            og_image="",
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
            ("some_dir/path", [], ["file1", "file2", "file3"])
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
        actual = list(buildEntries(self.token))
        assert expected == actual

        self.mock_buildFileDictHelper.assert_any_call(
            Path("some_dir/path"), "file1", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("some_dir/path"), "file2", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("some_dir/path"), "file3", self.token
        )

    def test_no_valid_files(self):
        self.mock_buildFileDictHelper.return_value = None

        expected = []
        actual = list(buildEntries(self.token))
        assert expected == actual

        self.mock_buildFileDictHelper.assert_any_call(
            Path("some_dir/path"), "file1", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("some_dir/path"), "file2", self.token
        )
        self.mock_buildFileDictHelper.assert_any_call(
            Path("some_dir/path"), "file3", self.token
        )


class TestBuildS3Entries:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        self.mock_hashed_filename = mocker.patch("waiter.hashed_filename")
        self.mock_buildWaiterPath = mocker.patch("waiter.buildWaiterPath")
        mocker.patch("waiter.MEDIAVIEWER_SUFFIX", "mv-encoded")
        self.mock_hashed_filename.return_value = "hashPath"
        self.mock_buildWaiterPath.return_value = "waiterPath"

        self.token = {
            "path": "s3://bucket/prefix/Movie.Name/",
            "filename": "Movie.Name",
            "guid": "asdf1234",
            "ismovie": True,
            "displayname": "Movie Name",
            "videoprogresses": [],
            "download_link": (
                "https://s3.example.com/bucket/prefix/Movie.Name/"
                "Movie.Name.mv-encoded.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256"
                "&X-Amz-Signature=abc123"
            ),
        }

    def test_is_s3_token(self):
        assert is_s3_token(self.token)
        assert not is_s3_token({"path": "/local/path"})
        assert not is_s3_token({})

    def test_build_entries_s3_movie(self):
        entries = list(buildEntries(self.token))
        assert len(entries) == 1
        entry = entries[0]
        assert entry["isS3"] is True
        assert entry["unhashedPath"] == self.token["download_link"]
        assert entry["subtitleFiles"] == []
        assert entry["subtitleWaiterPath"] == ""
        assert entry["filename"] == "Movie.Name"
        assert entry["hashedWaiterPath"] == "hashPath"
        assert entry["ismovie"] is True
        assert entry["displayName"] == "Movie Name"
        self.mock_hashed_filename.assert_called_once_with(
            "Movie.Name/Movie.Name.mv-encoded.mp4"
        )
        self.mock_buildWaiterPath.assert_any_call(
            "file", "asdf1234", "hashPath", includeLastSlash=True
        )
        self.mock_buildWaiterPath.assert_any_call(
            "stream", "asdf1234", "hashPath", includeLastSlash=True
        )

    def test_build_entries_s3_tv(self):
        self.token["ismovie"] = False
        self.token["filename"] = "Show.Name.S01E01.mv-encoded.mp4"
        self.token["path"] = "s3://bucket/prefix/Show.Name/"
        self.token["download_link"] = (
            "https://s3.example.com/bucket/prefix/Show.Name/"
            "Show.Name.S01E01.mv-encoded.mp4?X-Amz-Signature=abc123"
        )

        entries = list(buildEntries(self.token))
        assert len(entries) == 1
        assert entries[0]["isS3"] is True
        assert entries[0]["ismovie"] is False
        self.mock_hashed_filename.assert_called_once_with(
            "Show.Name.S01E01.mv-encoded.mp4/Show.Name.S01E01.mv-encoded.mp4"
        )

    def test_build_s3_file_dict_encoded_filename(self):
        self.token["download_link"] = (
            "https://s3.example.com/bucket/prefix/Movie.Name/"
            "Movie.Name%20Part.mv-encoded.mp4?X-Amz-Signature=abc123"
        )

        entry = _buildS3FileDict(self.token)
        assert entry["filename"] == "Movie.Name Part"

    def test_build_entries_s3_missing_download_link(self):
        self.token["download_link"] = None

        with pytest.raises(Exception):
            list(buildEntries(self.token))

    def test_build_entries_s3_movie_with_subtitles(self):
        self.token["subtitle_files"] = [
            "https://s3.example.com/bucket/prefix/Movie.Name/"
            "Movie.Name.mv-encoded.mp4.mv-encoded.mp4-0.vtt?X-Amz-Signature=abc123",
            "https://s3.example.com/bucket/prefix/Movie.Name/"
            "Movie.Name.mv-encoded.mp4.mv-encoded.mp4-1.vtt?X-Amz-Signature=abc123",
        ]

        entries = list(buildEntries(self.token))
        assert len(entries) == 1
        entry = entries[0]
        assert len(entry["subtitleFiles"]) == 2
        first, second = entry["subtitleFiles"]
        assert first.path == self.token["subtitle_files"][0]
        assert first.hashed_filename == "hashPath"
        assert first.waiter_path == "waiterPath"
        assert second.path == self.token["subtitle_files"][1]
        assert entry["subtitleWaiterPath"] == "waiterPath"
        self.mock_hashed_filename.assert_any_call(
            "Movie.Name/Movie.Name.mv-encoded.mp4.mv-encoded.mp4-0.vtt"
        )
        self.mock_hashed_filename.assert_any_call(
            "Movie.Name/Movie.Name.mv-encoded.mp4.mv-encoded.mp4-1.vtt"
        )
        self.mock_buildWaiterPath.assert_any_call("file", "asdf1234", "hashPath")

    def test_build_entries_s3_movie_with_encoded_subtitle_filename(self):
        self.token["subtitle_files"] = [
            "https://s3.example.com/bucket/prefix/Movie.Name/"
            "Movie.Name%20Part.mv-encoded.mp4.mv-encoded.mp4-0.vtt?X-Amz-Signature=abc123",
        ]

        entries = list(buildEntries(self.token))
        entry = entries[0]
        assert len(entry["subtitleFiles"]) == 1
        self.mock_hashed_filename.assert_any_call(
            "Movie.Name/Movie.Name Part.mv-encoded.mp4.mv-encoded.mp4-0.vtt"
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
        actual = _buildFileDictHelper("some_dir", "filename.mp4", self.token)
        assert expected == actual
        assert not self.mock_buildWaiterPath.called
        assert not self.mock_hashed_filename.called
        assert not self.mock_isAlfredEncoding.called

    def test_file_not_streamable(self):
        self.mock_getsize.return_value = 100000000

        expected = None
        actual = _buildFileDictHelper("some_dir", "filename.mkv", self.token)
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
                "rawSize": 100,
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
            Path("unhashed/path/to/file"), "file", 100
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
            Path("unhashed/path/to/file"), "file", 100
        )

    def test_s3_file_redirects(self):
        self.mock_buildEntries.return_value = [
            {
                "hashedWaiterPath": "hashPath",
                "unhashedPath": (
                    "https://s3.example.com/bucket/prefix/Movie.Name/"
                    "Movie.Name.mv-encoded.mp4?X-Amz-Signature=abc123"
                ),
                "rawSize": None,
                "isS3": True,
            }
        ]

        actual = send_file_for_download("guid", "hashPath")
        assert actual.status_code == 307
        assert (
            actual.headers["Location"]
            == "https://s3.example.com/bucket/prefix/Movie.Name/"
            "Movie.Name.mv-encoded.mp4?X-Amz-Signature=abc123"
        )
        assert not self.mock_send_file_partial.called

    def test_s3_subtitle_redirects(self):
        subtitle = Subtitle(
            path=(
                "https://s3.example.com/bucket/prefix/Movie.Name/"
                "Movie.Name.mv-encoded.mp4.mv-encoded.mp4-0.vtt?X-Amz-Signature=abc123"
            ),
            hashed_filename="subtitleHashPath",
            waiter_path="subtitleWaiterPath",
        )
        self.mock_buildEntries.return_value = [
            {
                "hashedWaiterPath": "hashPath",
                "unhashedPath": (
                    "https://s3.example.com/bucket/prefix/Movie.Name/"
                    "Movie.Name.mv-encoded.mp4?X-Amz-Signature=abc123"
                ),
                "rawSize": None,
                "isS3": True,
                "subtitleFiles": [subtitle],
            }
        ]

        actual = send_file_for_download("guid", "subtitleHashPath")
        assert actual.status_code == 307
        assert actual.headers["Location"] == subtitle.path
        assert not self.mock_send_file_partial.called

    def test_local_subtitle_served_from_disk(self, tmp_path):
        subtitle_file = tmp_path / "subtitle.vtt"
        subtitle_file.write_bytes(b"WEBVTT")
        subtitle = Subtitle(
            path=subtitle_file,
            hashed_filename="subtitleHashPath",
            waiter_path="subtitleWaiterPath",
        )
        self.mock_buildEntries.return_value = [
            {
                "hashedWaiterPath": "hashPath",
                "unhashedPath": Path("unhashed/path/to/file"),
                "rawSize": 100,
                "subtitleFiles": [subtitle],
            }
        ]

        actual = send_file_for_download("guid", "subtitleHashPath")
        assert actual == self.mock_send_file_partial.return_value
        self.mock_send_file_partial.assert_called_once_with(
            subtitle_file, "subtitle.vtt", 6
        )


class TestGetFile:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        self.EXTERNAL_MEDIAVIEWER_BASE_URL_patcher = mocker.patch(
            "waiter.EXTERNAL_MEDIAVIEWER_BASE_URL", "BASE_URL"
        )
        self.WAITER_OFFSET_URL = mocker.patch("waiter.WAITER_OFFSET_URL", "OFFSET_URL")
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
        self.mock_buildEntries.return_value = []

        self.mock_getMediaGenres = mocker.patch("waiter.getMediaGenres")
        self.mock_getMediaGenres.return_value = ("tv_genres", "movie_genres")

        self.mock_get_collections = mocker.patch("waiter.get_collections")
        self.mock_get_collections.return_value = ((1, "Test Name"),)

        self.token = {
            "ismovie": False,
            "filename": "test_filename.mp4",
            "path": "test/path",
            "displayname": "test_displayname",
            "tv_id": 123,
            "tv_name": "test_pathname",
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
            tv_id=123,
            tv_name="test_pathname",
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            guid="guid",
            offsetUrl="OFFSET_URL",
            next_link=None,
            previous_link=None,
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            collections=((1, "Test Name"),),
            binge_mode=True,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
            is_mcp=False,
            og_title="",
            og_type="",
            og_url="",
            og_image="",
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
            tv_id=123,
            tv_name="test_pathname",
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            guid="guid",
            offsetUrl="OFFSET_URL",
            next_link="BASE_URL/autoplaydownloadlink/123/",
            previous_link="BASE_URL/autoplaydownloadlink/234/",
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            collections=((1, "Test Name"),),
            binge_mode=True,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
            is_mcp=False,
            og_title="",
            og_type="",
            og_url="",
            og_image="",
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
            tv_id=123,
            tv_name="test_pathname",
            username="some.user",
            mediaviewer_base_url="BASE_URL",
            guid="guid",
            offsetUrl="OFFSET_URL",
            next_link=None,
            previous_link=None,
            tv_genres="tv_genres",
            movie_genres="movie_genres",
            collections=((1, "Test Name"),),
            binge_mode=False,
            donation_site_name="",
            donation_site_url="",
            theme=DEFAULT_THEME,
            is_mcp=False,
            og_title="",
            og_type="",
            og_url="",
            og_image="",
        )


class TestGetStatus:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker, temp_directory):
        self.dir = temp_directory
        mocker.patch("waiter.BASE_PATH", str(self.dir))

        self.media_dirs = []
        for i in range(3):
            media_dir = self.dir / str(i)
            media_dir.mkdir()
            self.media_dirs.append(media_dir)

        self.mock_jsonify = mocker.patch("waiter.jsonify")

    def test_good(self, mocker):
        mocker.patch("waiter.MEDIA_DIRS", [str(x) for x in self.media_dirs])

        expected = ({"status": True}, 200)
        actual = get_status()
        assert expected == actual

    def test_bad(self, mocker):
        self.media_dirs.append("/does/not/exist")
        mocker.patch("waiter.MEDIA_DIRS", [str(x) for x in self.media_dirs])

        expected = ({"status": False}, 500)
        actual = get_status()
        assert expected == actual
