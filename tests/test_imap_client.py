import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imap_client import AutoIMAPClient

class TestAutoIMAPClient(unittest.TestCase):

    def setUp(self):
        self.email = "test@example.com"
        self.password = "password"
        self.client = AutoIMAPClient(self.email, self.password)

    def test_guess_server(self):
        # Test standard guessing
        servers = self.client._guess_server()
        self.assertIn("imap.example.com", servers)
        self.assertIn("mail.example.com", servers)
        
        # Test common provider
        gmail_client = AutoIMAPClient("user@gmail.com", "pass")
        gmail_servers = gmail_client._guess_server()
        self.assertIn("imap.gmail.com", gmail_servers)

    @patch('urllib.request.urlopen')
    def test_thunderbird_config(self, mock_urlopen):
        # Mock XML response
        xml_content = b"""
        <clientConfig>
            <emailProvider id="example.com">
                <incomingServer type="imap">
                    <hostname>imap.config.example.com</hostname>
                    <port>993</port>
                    <socketType>SSL</socketType>
                </incomingServer>
            </emailProvider>
        </clientConfig>
        """
        
        from io import BytesIO
        class MockResponse(BytesIO):
            def __init__(self, content, status):
                super().__init__(content)
                self.status = status
        
        mock_urlopen.return_value.__enter__.return_value = MockResponse(xml_content, 200)

        config = self.client._lookup_thunderbird_config()
        self.assertEqual(config, "imap.config.example.com")

    @patch('imaplib.IMAP4_SSL')
    def test_connect_success(self, mock_imap):
        mock_conn = MagicMock()
        mock_imap.return_value = mock_conn
        
        # Test connecting to specific server
        result = self.client.connect("imap.test.com", verbose=False)
        self.assertTrue(result)
        mock_imap.assert_called_with("imap.test.com", 993, timeout=10)
        mock_conn.login.assert_called_with(self.email, self.password)
        self.assertEqual(self.client.server_address, "imap.test.com")

    @patch('imaplib.IMAP4_SSL')
    def test_connect_failure(self, mock_imap):
        import imaplib
        mock_imap.side_effect = imaplib.IMAP4.error("Connection failed")
        result = self.client.connect("imap.test.com", verbose=False)
        self.assertFalse(result)

    def test_list_folders_parsing(self):
        self.client.connection = MagicMock()
        # Mock response for list()
        # Format: (response_status, [b'(\\HasNoChildren) "/" "INBOX"', ...])
        self.client.connection.list.return_value = ('OK', [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasChildren) "/" "Sent"',
            b'(\\HasNoChildren) "/" "Trash"',
            b'(\\HasNoChildren) "/" "[Gmail]/Spam"', # Should be ignored
            b'(\\HasNoChildren) "/" "[Gmail]/Todos os e-mails"', # Should be ignored
            b'(\\HasNoChildren) "/" "[Gmail]/All Mail"' # Should be ignored
        ])
        
        folders = self.client.list_folders()
        self.assertIn("INBOX", folders)
        self.assertIn("Sent", folders)
        self.assertIn("Trash", folders)
        # Spam should be filtered out by default logic if it contains 'spam'
        # The logic is: if ('spam' in lower_name or 'junk' in lower_name or 'bulk' in lower_name) and 'trash' not in lower_name: continue
        self.assertNotIn("[Gmail]/Spam", folders)
        self.assertNotIn("[Gmail]/Todos os e-mails", folders)
        self.assertNotIn("[Gmail]/All Mail", folders)

    def test_select_folder(self):
        self.client.connection = MagicMock()
        self.client.connection.select.return_value = ('OK', [b'1'])
        
        # Test normal folder
        self.assertTrue(self.client.select_folder("INBOX"))
        self.client.connection.select.assert_called_with("INBOX", readonly=True)
        
        # Test folder with spaces
        self.assertTrue(self.client.select_folder("Sent Items"))
        self.client.connection.select.assert_called_with('"Sent Items"', readonly=True)

if __name__ == '__main__':
    unittest.main()
