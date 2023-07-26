import pytest
import mock
from utils import (
    humansize,
    checkForValidToken,
    getMediaGenres,
    parseRangeHeaders,
)
from settings import REQUESTS_TIMEOUT


class TestHumanSize:
    def test_0(self):
        val = 0

        expected = "0 B"
        actual = humansize(val)
        assert expected == actual

    def test_123(self):
        val = 123

        expected = "123 B"
        actual = humansize(val)
        assert expected == actual

    def test_1234(self):
        val = 1234

        expected = "1.21 KB"
        actual = humansize(val)
        assert expected == actual

    def test_12345(self):
        val = 12345

        expected = "12.06 KB"
        actual = humansize(val)
        assert expected == actual

    def test_123456(self):
        val = 123456

        expected = "120.56 KB"
        actual = humansize(val)
        assert expected == actual

    def test_1234567(self):
        val = 1234567

        expected = "1.18 MB"
        actual = humansize(val)
        assert expected == actual

    def test_12345678(self):
        val = 12345678

        expected = "11.77 MB"
        actual = humansize(val)
        assert expected == actual

    def test_123456789(self):
        val = 123456789

        expected = "117.74 MB"
        actual = humansize(val)
        assert expected == actual

    def test_1234567890(self):
        val = 1234567890

        expected = "1.15 GB"
        actual = humansize(val)
        assert expected == actual

    def test_12345678901(self):
        val = 12345678901

        expected = "11.5 GB"
        actual = humansize(val)
        assert expected == actual


class TestCheckForValidToken:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        self.mock_log = mocker.patch("utils.log")

        self.token = {"isvalid": True}
        self.guid = "abc123"

    def test_noToken(self):
        expected = "This token is invalid! Return to Movie or TV Show tab to generate a new one."
        actual = checkForValidToken({}, self.guid)
        assert expected == actual
        self.mock_log.warn.assert_called_once_with("Token is invalid GUID: abc123")

    def test_invalidToken(self):
        self.token["isvalid"] = False

        expected = "This token has expired! Return to Movie or TV Show tab to generate a new one."
        actual = checkForValidToken(self.token, self.guid)
        assert expected == actual
        self.mock_log.warn.assert_called_once_with("Token Expired GUID: abc123")

    def test_validToken(self):
        expected = None
        actual = checkForValidToken(self.token, self.guid)
        assert expected == actual
        assert not self.mock_log.warn.called


class TestGetMediaGenres:
    @pytest.fixture(autouse=True)
    def setUp(self, mocker):
        mocker.patch("utils.MEDIAVIEWER_BASE_URL", "base_url")

        self.mock_get = mocker.patch("utils.requests.get")

        self.mock_resp = mock.MagicMock()
        self.mock_resp.json.return_value = {
            "tv_genres": [
                [123, "Action"],
                [234, "Crime"],
                [345, "Drama"],
            ],
            "movie_genres": [
                [456, "History"],
                [567, "Biography"],
                [678, "Thriller"],
            ],
        }
        self.mock_get.return_value = self.mock_resp

        self.test_guid = "test_guid"

    def test_getMediaGenre(self):
        expected = (
            [
                ("Action", "base_url/tvshows/genre/123/"),
                ("Crime", "base_url/tvshows/genre/234/"),
                ("Drama", "base_url/tvshows/genre/345/"),
            ],
            [
                ("History", "base_url/movies/genre/456/"),
                ("Biography", "base_url/movies/genre/567/"),
                ("Thriller", "base_url/movies/genre/678/"),
            ],
        )
        actual = getMediaGenres(self.test_guid)

        self.mock_get.assert_called_once_with("base_url/ajaxgenres/test_guid/", timeout=REQUESTS_TIMEOUT)
        assert expected == actual


class TestParseRangeHeaders:
    @pytest.fixture(autouse=True)
    def setUp(self):
        self.file_size = 1234
        self.default_length = 500

    def test_first_500_bytes(self):
        length, byte1, byte2 = parseRangeHeaders(
            self.file_size, "0-", default_length=self.default_length
        )

        assert length == self.default_length
        assert byte1 == 0
        assert byte2 == 499

    def test_second_500_bytes(self):
        length, byte1, byte2 = parseRangeHeaders(
            self.file_size, "500-", default_length=self.default_length
        )

        assert length == self.default_length
        assert byte1 == 500
        assert byte2 == 999

    def test_all_except_first_500_bytes(self):
        self.default_length = 2000

        length, byte1, byte2 = parseRangeHeaders(
            self.file_size, "500-", default_length=self.default_length
        )

        assert length == 734
        assert byte1 == 500
        assert byte2 == 1233

    def test_last_500_bytes(self):
        self.default_length = 2000

        length, byte1, byte2 = parseRangeHeaders(
            self.file_size, "734-", default_length=self.default_length
        )

        assert length == 500
        assert byte1 == 734
        assert byte2 == 1233
