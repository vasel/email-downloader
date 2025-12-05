import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_downloader
from imap_client import AutoIMAPClient

class TestLogOutput(unittest.TestCase):
    
    @patch('email_downloader.AutoIMAPClient')
    @patch('email_downloader.ensure_directory')
    @patch('email_downloader.create_zip_archive')
    @patch('email_downloader.calculate_sha1')
    @patch('email_downloader.os.path.getsize')
    @patch('email_downloader.timed_input')
    @patch('builtins.open', new_callable=mock_open)
    @patch('email_downloader.click.echo')
    def test_log_connection_details(self, mock_echo, mock_file, mock_input, mock_getsize, mock_sha1, mock_zip, mock_ensure, MockClient):
        # Setup
        mock_input.return_value = 'y'
        mock_getsize.return_value = 100
        mock_sha1.return_value = "hash123"
        
        client_instance = MockClient.return_value
        client_instance.connect.return_value = True
        client_instance.server_address = "imap.success.com"
        client_instance.connection_attempts = [("imap.fail.com", "Timeout"), ("mail.fail.com", "Refused")]
        client_instance.list_folders.return_value = []
        
        # Run main (simulated)
        # We can't easily run main() because of the loop and click decorators.
        # Instead, we can extract the logging logic or simulate the flow.
        # But main is one big function.
        # Let's try to invoke main via click runner or just mock enough to reach the end.
        
        from click.testing import CliRunner
        runner = CliRunner()
        
        # We need to mock getpass too
        with patch('email_downloader.getpass.getpass', return_value="password"):
             result = runner.invoke(email_downloader.main, [
                 '--email', 'test@example.com',
                 '--password', 'password',
                 '--days', '1',
                 '--batch'
             ])
        
        # Check if file write was called with expected content
        # The file write happens for the checksum file
        
        # Check result
        if result.exit_code != 0:
            print(f"Output: {result.output}")
            print(f"Exception: {result.exception}")
            import traceback
            traceback.print_tb(result.exc_info[2])
            
        # Find the call to open that writes the checksum file
        # It ends with .txt
        handle = mock_file()
        
        # Collect all writes
        written_content = ""
        for call in handle.write.call_args_list:
            written_content += call[0][0]
            
        print(f"Written content: {written_content}")
            
        self.assertIn("Server Connected: imap.success.com", written_content)
        self.assertIn("Failed Connection Attempts:", written_content)
        self.assertIn("- imap.fail.com: Timeout", written_content)
        self.assertIn("- mail.fail.com: Refused", written_content)

if __name__ == '__main__':
    unittest.main()
