import unittest
import mock
from utils import (humansize,
                   checkForValidToken,
                   getMediaGenres,
                    )

class TestHumanSize(unittest.TestCase):
    def test_0(self):
        val = 0

        expected = '0 B'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_123(self):
        val = 123

        expected = '123 B'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_1234(self):
        val = 1234

        expected = '1.21 KB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_12345(self):
        val = 12345

        expected = '12.06 KB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_123456(self):
        val = 123456

        expected = '120.56 KB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_1234567(self):
        val = 1234567

        expected = '1.18 MB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_12345678(self):
        val = 12345678

        expected = '11.77 MB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_123456789(self):
        val = 123456789

        expected = '117.74 MB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_1234567890(self):
        val = 1234567890

        expected = '1.15 GB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

    def test_12345678901(self):
        val = 12345678901

        expected = '11.5 GB'
        actual = humansize(val)
        self.assertEqual(expected, actual)

class TestCheckForValidToken(unittest.TestCase):
    def setUp(self):
        self.log_patcher = mock.patch('utils.log')
        self.mock_log = self.log_patcher.start()

        self.token = {'isvalid': True}
        self.guid = 'abc123'

    def tearDown(self):
        self.log_patcher.stop()

    def test_noToken(self):
        expected = 'This token is invalid! Return to Movie or TV Show tab to generate a new one.'
        actual = checkForValidToken({}, self.guid)
        self.assertEqual(expected, actual)
        self.mock_log.warn.assert_called_once_with('Token is invalid GUID: abc123')

    def test_invalidToken(self):
        self.token['isvalid'] = False

        expected = 'This token has expired! Return to Movie or TV Show tab to generate a new one.'
        actual = checkForValidToken(self.token, self.guid)
        self.assertEqual(expected, actual)
        self.mock_log.warn.assert_called_once_with('Token Expired GUID: abc123')

    def test_validToken(self):
        expected = None
        actual = checkForValidToken(self.token, self.guid)
        self.assertEqual(expected, actual)
        self.assertFalse(self.mock_log.warn.called)

class TestGetMediaGenres(unittest.TestCase):
    def setUp(self):
        self.MEDIAVIEWER_BASE_URL_patcher = mock.patch('utils.MEDIAVIEWER_BASE_URL', 'base_url')
        self.MEDIAVIEWER_BASE_URL_patcher.start()

        self.get_patcher = mock.patch('utils.requests.get')
        self.mock_get = self.get_patcher.start()

        self.mock_resp = mock.MagicMock()
        self.mock_resp.json.return_value = {'tv_genres': [[123, 'Action'],
                                                          [234, 'Crime'],
                                                          [345, 'Drama'],
                                                          ],
                                            'movie_genres': [[456, 'History'],
                                                             [567, 'Biography'],
                                                             [678, 'Thriller'],
                                                             ]}
        self.mock_get.return_value = self.mock_resp

        self.test_guid = 'test_guid'

    def tearDown(self):
        self.MEDIAVIEWER_BASE_URL_patcher.stop()
        self.get_patcher.stop()

    def test_getMediaGenre(self):
        expected = ([('Action', 'base_url/tvshows/genre/123/'),
                     ('Crime', 'base_url/tvshows/genre/234/'),
                     ('Drama', 'base_url/tvshows/genre/345/')],
                    [('History', 'base_url/movies/genre/456/'),
                     ('Biography', 'base_url/movies/genre/567/'),
                     ('Thriller', 'base_url/movies/genre/678/')])
        actual = getMediaGenres(self.test_guid)

        self.mock_get.assert_called_once_with('base_url/ajaxgenres/test_guid/')
        self.assertEqual(expected, actual)
