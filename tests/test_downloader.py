import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import threading

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import specific functions to test
# Note: Testing the main loop is hard, so we focus on helper functions and worker tasks
from email_downloader import download_email_task

class TestEmailDownloader(unittest.TestCase):

    @patch('email_downloader.AutoIMAPClient')
    @patch('email_downloader.ensure_directory')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_download_email_task_success(self, mock_file, mock_ensure_dir, MockClient):
        # Setup Mock Client
        client_instance = MockClient.return_value
        client_instance.connect.return_value = True
        client_instance.select_folder.return_value = True
        client_instance.fetch_message_id.return_value = "msg-id-123"
        client_instance.fetch_email_content.return_value = b"Email Content"
        
        # Setup args
        email = "test@example.com"
        password = "pass"
        server = "imap.test.com"
        folder = "INBOX"
        email_id = b"1"
        output_dir = "/tmp/downloads"
        seen_ids = set()
        seen_lock = threading.Lock()
        
        success, error = download_email_task(email, password, server, folder, email_id, output_dir, seen_ids, seen_lock)
        
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertIn("msg-id-123", seen_ids)
        
        # Verify file write
        mock_file.assert_called()
        handle = mock_file()
        handle.write.assert_called_with(b"Email Content")

    @patch('email_downloader.AutoIMAPClient')
    def test_download_email_task_connection_fail(self, MockClient):
        client_instance = MockClient.return_value
        client_instance.connect.return_value = False
        
        success, error = download_email_task("e", "p", "s", "f", b"1", "o")
        
        self.assertFalse(success)
        self.assertEqual(error, "Connection failed")

    @patch('email_downloader.AutoIMAPClient')
    def test_download_email_task_duplicate(self, MockClient):
        client_instance = MockClient.return_value
        client_instance.connect.return_value = True
        client_instance.select_folder.return_value = True
        client_instance.fetch_message_id.return_value = "msg-id-123"
        
        seen_ids = {"msg-id-123"}
        seen_lock = threading.Lock()
        
        success, error = download_email_task("e", "p", "s", "f", b"1", "o", seen_ids, seen_lock)
        
        self.assertTrue(success)
        self.assertEqual(error, "SKIPPED")
        # Should not fetch content
        client_instance.fetch_email_content.assert_not_called()

if __name__ == '__main__':
    unittest.main()
