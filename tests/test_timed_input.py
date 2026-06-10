import unittest
from unittest.mock import patch, MagicMock, call
import os
import sys
import io

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestTimedInput(unittest.TestCase):
    """Tests for timed_input function with mocked msvcrt and time."""

    def _run_timed_input(self, prompt, timeout, default, time_values, kbhit_values, getwche_values):
        """
        Helper to run timed_input with controlled time and keyboard mocks.

        Args:
            time_values: sequence of floats returned by time.time()
            kbhit_values: sequence of booleans returned by msvcrt.kbhit()
            getwche_values: sequence of chars returned by msvcrt.getwche()
        """
        with patch('email_downloader.msvcrt') as mock_msvcrt, \
             patch('email_downloader.time') as mock_time, \
             patch('email_downloader.sys') as mock_sys:

            mock_time.time = MagicMock(side_effect=time_values)
            mock_time.sleep = MagicMock()
            mock_msvcrt.kbhit = MagicMock(side_effect=kbhit_values)
            mock_msvcrt.getwche = MagicMock(side_effect=getwche_values)
            mock_sys.stdout = MagicMock()

            from email_downloader import timed_input
            return timed_input(prompt, timeout=timeout, default=default)

    def test_timeout_returns_default_y(self):
        """When no key is pressed and timeout expires, should return default 'y'."""
        # time.time() calls: start_time=0, then loop iterations at 0,1,...,11
        # We need enough calls: start(0), loop: remaining check(1), remaining check(2)...until <=0
        # Each loop iteration calls time.time() twice (for remaining calc) + sleep
        # Actually looking at the code: time.time() is called once for start_time,
        # then once per loop iteration for remaining calc.
        # Let's simulate: start=0, then iterations at 2, 4, 6, 8, 10, 11 (timeout=10)
        time_seq = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 11.0]
        kbhit_seq = [False, False, False, False, False]  # Never pressed
        
        result = self._run_timed_input("Test?", 10, 'y', time_seq, kbhit_seq, [])
        self.assertEqual(result, 'y')

    def test_timeout_returns_default_n(self):
        """When default is 'n' and timeout expires, should return 'n'."""
        time_seq = [0.0, 5.0, 11.0]
        kbhit_seq = [False]
        
        result = self._run_timed_input("Test?", 10, 'n', time_seq, kbhit_seq, [])
        self.assertEqual(result, 'n')

    def test_user_presses_y(self):
        """When user presses 'y' before timeout, should return 'y'."""
        time_seq = [0.0, 2.0]  # start=0, first loop at 2s
        kbhit_seq = [True]
        getwche_seq = ['y']
        
        result = self._run_timed_input("Test?", 10, 'n', time_seq, kbhit_seq, getwche_seq)
        self.assertEqual(result, 'y')

    def test_user_presses_n(self):
        """When user presses 'n' before timeout, should return 'n'."""
        time_seq = [0.0, 1.0]
        kbhit_seq = [True]
        getwche_seq = ['n']
        
        result = self._run_timed_input("Test?", 10, 'y', time_seq, kbhit_seq, getwche_seq)
        self.assertEqual(result, 'n')

    def test_user_presses_enter_returns_default(self):
        """When user presses Enter without typing, should return default."""
        time_seq = [0.0, 1.0]
        kbhit_seq = [True]
        getwche_seq = ['\r']
        
        result = self._run_timed_input("Test?", 10, 'y', time_seq, kbhit_seq, getwche_seq)
        self.assertEqual(result, 'y')

    def test_user_presses_enter_default_n(self):
        """When user presses Enter with default 'n', should return 'n'."""
        time_seq = [0.0, 1.0]
        kbhit_seq = [True]
        getwche_seq = ['\r']
        
        result = self._run_timed_input("Test?", 10, 'n', time_seq, kbhit_seq, getwche_seq)
        self.assertEqual(result, 'n')

    def test_countdown_updates_display(self):
        """Verify that the countdown display is updated as time passes."""
        with patch('email_downloader.msvcrt') as mock_msvcrt, \
             patch('email_downloader.time') as mock_time, \
             patch('email_downloader.sys') as mock_sys:

            # Simulate: start=0, loops at 1s, 3s, 5s, then timeout at 11s
            mock_time.time = MagicMock(side_effect=[0.0, 1.0, 3.0, 5.0, 11.0])
            mock_time.sleep = MagicMock()
            mock_msvcrt.kbhit = MagicMock(side_effect=[False, False, False])
            mock_stdout = MagicMock()
            mock_sys.stdout = mock_stdout

            from email_downloader import timed_input
            result = timed_input("Q?", timeout=10, default='y')

            # Check that countdown was written to stdout with decreasing seconds
            write_calls = [str(c) for c in mock_stdout.write.call_args_list]
            # Should contain countdown numbers (9, 7, 5, then 0 and -> y)
            countdown_text = ''.join(str(c) for c in write_calls)
            self.assertIn('[9s]', countdown_text)
            self.assertIn('[5s]', countdown_text)
            self.assertIn('-> y', countdown_text)
            self.assertEqual(result, 'y')

    def test_sleep_called_between_checks(self):
        """Verify that time.sleep is called to prevent CPU hogging."""
        with patch('email_downloader.msvcrt') as mock_msvcrt, \
             patch('email_downloader.time') as mock_time, \
             patch('email_downloader.sys') as mock_sys:

            mock_time.time = MagicMock(side_effect=[0.0, 5.0, 11.0])
            mock_time.sleep = MagicMock()
            mock_msvcrt.kbhit = MagicMock(side_effect=[False])
            mock_sys.stdout = MagicMock()

            from email_downloader import timed_input
            timed_input("Q?", timeout=10, default='y')

            mock_time.sleep.assert_called_with(0.25)

    def test_prompt_shows_default_value(self):
        """Verify that the prompt includes the default value."""
        with patch('email_downloader.msvcrt') as mock_msvcrt, \
             patch('email_downloader.time') as mock_time, \
             patch('email_downloader.sys') as mock_sys:

            mock_time.time = MagicMock(side_effect=[0.0, 11.0])
            mock_time.sleep = MagicMock()
            mock_msvcrt.kbhit = MagicMock(side_effect=[])
            mock_stdout = MagicMock()
            mock_sys.stdout = mock_stdout

            from email_downloader import timed_input
            timed_input("Create ZIP? (y/n)", timeout=10, default='y')

            write_calls = ''.join(str(c) for c in mock_stdout.write.call_args_list)
            self.assertIn('default: y', write_calls)
            self.assertIn('Create ZIP? (y/n)', write_calls)

    def test_zero_timeout_returns_immediately(self):
        """With timeout=0, should return default immediately."""
        time_seq = [0.0, 0.0]
        
        result = self._run_timed_input("Test?", 0, 'n', time_seq, [], [])
        self.assertEqual(result, 'n')


if __name__ == '__main__':
    unittest.main()
