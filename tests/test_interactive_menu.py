import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import threading

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from interactive_menu import DownloadSettings, InteractiveMenu
from error_logger import ErrorLogger
import tempfile
import shutil


class TestDownloadSettings(unittest.TestCase):

    def test_defaults(self):
        s = DownloadSettings()
        self.assertFalse(s.do_zip)
        self.assertEqual(s.max_retries, 0)
        self.assertFalse(s.should_stop)
        self.assertFalse(s.zip_configured)

    def test_custom_init(self):
        s = DownloadSettings(do_zip=True, max_retries=5)
        self.assertTrue(s.do_zip)
        self.assertEqual(s.max_retries, 5)

    def test_repr(self):
        s = DownloadSettings(do_zip=True, max_retries=3)
        r = repr(s)
        self.assertIn("do_zip=True", r)
        self.assertIn("max_retries=3", r)
        self.assertIn("should_stop=False", r)
        self.assertIn("zip_configured=False", r)

    def test_mutable_fields(self):
        s = DownloadSettings()
        s.do_zip = True
        s.max_retries = 10
        s.should_stop = True
        s.zip_configured = True
        self.assertTrue(s.do_zip)
        self.assertEqual(s.max_retries, 10)
        self.assertTrue(s.should_stop)
        self.assertTrue(s.zip_configured)


class TestInteractiveMenu(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.settings = DownloadSettings()
        self.error_logger = ErrorLogger(self.test_dir)
        self.shutdown_event = threading.Event()
        self.menu = InteractiveMenu(self.settings, self.error_logger, self.shutdown_event)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --- Toggle ZIP ---

    def test_toggle_zip_on(self):
        self.assertFalse(self.settings.do_zip)
        self.menu._toggle_zip()
        self.assertTrue(self.settings.do_zip)
        self.assertTrue(self.settings.zip_configured)

    def test_toggle_zip_off(self):
        self.settings.do_zip = True
        self.menu._toggle_zip()
        self.assertFalse(self.settings.do_zip)
        self.assertTrue(self.settings.zip_configured)

    def test_toggle_zip_double(self):
        self.menu._toggle_zip()
        self.assertTrue(self.settings.do_zip)
        self.menu._toggle_zip()
        self.assertFalse(self.settings.do_zip)

    # --- Set retries ---

    @patch.object(InteractiveMenu, '_read_menu_choice', return_value='5')
    def test_set_retries(self, mock_input):
        self.menu._set_retries()
        self.assertEqual(self.settings.max_retries, 5)

    @patch.object(InteractiveMenu, '_read_menu_choice', return_value='0')
    def test_set_retries_zero(self, mock_input):
        self.settings.max_retries = 3
        self.menu._set_retries()
        self.assertEqual(self.settings.max_retries, 0)

    @patch.object(InteractiveMenu, '_read_menu_choice', return_value='abc')
    def test_set_retries_invalid(self, mock_input):
        original = self.settings.max_retries
        self.menu._set_retries()
        self.assertEqual(self.settings.max_retries, original)

    @patch.object(InteractiveMenu, '_read_menu_choice', return_value='-1')
    def test_set_retries_negative(self, mock_input):
        original = self.settings.max_retries
        self.menu._set_retries()
        self.assertEqual(self.settings.max_retries, original)

    # --- Stop confirmation ---

    @patch.object(InteractiveMenu, '_read_menu_choice', return_value='y')
    def test_confirm_stop_yes(self, mock_input):
        result = self.menu._confirm_stop()
        self.assertTrue(result)
        self.assertTrue(self.settings.should_stop)
        self.assertTrue(self.shutdown_event.is_set())

    @patch.object(InteractiveMenu, '_read_menu_choice', return_value='N')
    def test_confirm_stop_no(self, mock_input):
        result = self.menu._confirm_stop()
        self.assertFalse(result)
        self.assertFalse(self.settings.should_stop)
        self.assertFalse(self.shutdown_event.is_set())

    @patch.object(InteractiveMenu, '_read_menu_choice', return_value='')
    def test_confirm_stop_default_no(self, mock_input):
        """Empty input (just pressing Enter) should default to NOT stopping."""
        result = self.menu._confirm_stop()
        self.assertFalse(result)
        self.assertFalse(self.settings.should_stop)
        self.assertFalse(self.shutdown_event.is_set())

    # --- Show error log ---

    def test_show_error_log_empty(self):
        """Should not crash when there are no errors."""
        self.menu._show_error_log()  # Smoke test

    def test_show_error_log_with_entries(self):
        """Should not crash when there are errors."""
        self.error_logger.log("INBOX", b"1", "test error")
        self.error_logger.log("Sent", b"2", "another error")
        self.menu._show_error_log()  # Smoke test

    # --- Full menu flow ---

    @patch.object(InteractiveMenu, '_read_menu_choice')
    def test_show_menu_toggle_zip_and_close(self, mock_input):
        """Simulate: select option 1 (toggle zip), then 0 (close)."""
        mock_input.side_effect = ['1', '0']
        self.menu.show()
        self.assertTrue(self.settings.do_zip)
        self.assertTrue(self.settings.zip_configured)

    @patch.object(InteractiveMenu, '_read_menu_choice')
    def test_show_menu_set_retries_and_close(self, mock_input):
        """Simulate: select option 2 (set retries to 3), then 0 (close)."""
        mock_input.side_effect = ['2', '3', '0']
        self.menu.show()
        self.assertEqual(self.settings.max_retries, 3)

    @patch.object(InteractiveMenu, '_read_menu_choice')
    def test_show_menu_stop_confirmed(self, mock_input):
        """Simulate: select option 4 (stop), confirm with 'y'."""
        mock_input.side_effect = ['4', 'y']
        self.menu.show()
        self.assertTrue(self.settings.should_stop)
        self.assertTrue(self.shutdown_event.is_set())

    @patch.object(InteractiveMenu, '_read_menu_choice')
    def test_show_menu_stop_cancelled(self, mock_input):
        """Simulate: select option 4 (stop), cancel with 'n', then close."""
        mock_input.side_effect = ['4', 'n', '0']
        self.menu.show()
        self.assertFalse(self.settings.should_stop)
        self.assertFalse(self.shutdown_event.is_set())

    @patch.object(InteractiveMenu, '_read_menu_choice')
    def test_show_menu_invalid_then_close(self, mock_input):
        """Simulate: invalid option, then close."""
        mock_input.side_effect = ['9', '0']
        self.menu.show()
        # Nothing should change
        self.assertFalse(self.settings.do_zip)

    @patch.object(InteractiveMenu, '_read_menu_choice')
    def test_show_menu_view_errors(self, mock_input):
        """Simulate: view error log (option 3), then close."""
        self.error_logger.log("INBOX", b"1", "err")
        mock_input.side_effect = ['3', '0']
        self.menu.show()  # Smoke test - should not crash

    # --- Menu text ---

    def test_menu_text_contains_all_options(self):
        self.assertIn("Toggle ZIP", InteractiveMenu.MENU_TEXT)
        self.assertIn("retries", InteractiveMenu.MENU_TEXT)
        self.assertIn("error log", InteractiveMenu.MENU_TEXT)
        self.assertIn("Stop processing", InteractiveMenu.MENU_TEXT)
        self.assertIn("Close menu", InteractiveMenu.MENU_TEXT)


if __name__ == '__main__':
    unittest.main()
