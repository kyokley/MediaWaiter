import unittest
import mock
from utils import (humansize,
                   checkForValidToken,
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
