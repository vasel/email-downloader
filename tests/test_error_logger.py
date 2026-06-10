import unittest
import os
import shutil
import tempfile
import threading
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from error_logger import ErrorLogger


class TestErrorLogger(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.logger = ErrorLogger(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --- Basic functionality ---

    def test_log_adds_entry(self):
        self.logger.log("INBOX", b"123", "Connection timeout")
        entries = self.logger.get_all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["folder"], "INBOX")
        self.assertEqual(entries[0]["email_id"], "123")
        self.assertEqual(entries[0]["error"], "Connection timeout")

    def test_log_accepts_str_email_id(self):
        self.logger.log("Sent", "456", "Some error")
        entries = self.logger.get_all()
        self.assertEqual(entries[0]["email_id"], "456")

    def test_count(self):
        self.assertEqual(self.logger.count(), 0)
        self.logger.log("INBOX", b"1", "err1")
        self.logger.log("INBOX", b"2", "err2")
        self.logger.log("Sent", b"3", "err3")
        self.assertEqual(self.logger.count(), 3)

    def test_get_all(self):
        for i in range(5):
            self.logger.log("INBOX", str(i).encode(), f"error_{i}")
        all_entries = self.logger.get_all()
        self.assertEqual(len(all_entries), 5)
        # Verify order
        for i, entry in enumerate(all_entries):
            self.assertEqual(entry["email_id"], str(i))

    def test_get_recent(self):
        for i in range(30):
            self.logger.log("INBOX", str(i).encode(), f"error_{i}")
        recent = self.logger.get_recent(5)
        self.assertEqual(len(recent), 5)
        # Should be the last 5 entries
        self.assertEqual(recent[0]["email_id"], "25")
        self.assertEqual(recent[-1]["email_id"], "29")

    def test_get_recent_fewer_than_n(self):
        self.logger.log("INBOX", b"1", "err")
        recent = self.logger.get_recent(20)
        self.assertEqual(len(recent), 1)

    # --- File I/O ---

    def test_file_written(self):
        self.logger.log("INBOX", b"100", "Connection lost")
        self.assertTrue(os.path.exists(self.logger.log_path))

    def test_file_format(self):
        self.logger.log("INBOX", b"100", "Connection lost")
        self.logger.log("Sent", b"200", "Empty content")

        with open(self.logger.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertEqual(len(lines), 2)
        # Verify first line structure
        self.assertIn("Folder: INBOX", lines[0])
        self.assertIn("UID: 100", lines[0])
        self.assertIn("Error: Connection lost", lines[0])
        self.assertTrue(lines[0].startswith("["))
        # Verify second line
        self.assertIn("Folder: Sent", lines[1])
        self.assertIn("UID: 200", lines[1])

    def test_file_appends(self):
        """Verify that subsequent logs append to the same file."""
        self.logger.log("INBOX", b"1", "err1")
        self.logger.log("INBOX", b"2", "err2")

        with open(self.logger.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)

    def test_log_path_property(self):
        expected = os.path.join(self.test_dir, "error_log.txt")
        self.assertEqual(self.logger.log_path, expected)

    def test_custom_filename(self):
        logger = ErrorLogger(self.test_dir, filename="custom_errors.log")
        logger.log("INBOX", b"1", "test")
        expected = os.path.join(self.test_dir, "custom_errors.log")
        self.assertEqual(logger.log_path, expected)
        self.assertTrue(os.path.exists(expected))

    # --- Thread safety ---

    def test_thread_safety(self):
        """Multiple threads logging simultaneously should not crash or lose entries."""
        num_threads = 10
        entries_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def worker(thread_id):
            barrier.wait()
            for i in range(entries_per_thread):
                self.logger.log("INBOX", f"t{thread_id}_e{i}".encode(), f"error from thread {thread_id}")

        threads = []
        for t_id in range(num_threads):
            t = threading.Thread(target=worker, args=(t_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        expected_count = num_threads * entries_per_thread
        self.assertEqual(self.logger.count(), expected_count)

        # Verify file has the right number of lines
        with open(self.logger.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), expected_count)

    # --- format_entry ---

    def test_format_entry(self):
        self.logger.log("INBOX", b"42", "Timeout occurred")
        entry = self.logger.get_all()[0]
        formatted = self.logger.format_entry(entry)
        self.assertIn("Folder: INBOX", formatted)
        self.assertIn("UID: 42", formatted)
        self.assertIn("Error: Timeout occurred", formatted)

    # --- Edge cases ---

    def test_empty_error_message(self):
        self.logger.log("INBOX", b"1", "")
        entries = self.logger.get_all()
        self.assertEqual(entries[0]["error"], "")

    def test_get_all_returns_copy(self):
        """Modifying returned list should not affect internal state."""
        self.logger.log("INBOX", b"1", "err")
        all_entries = self.logger.get_all()
        all_entries.clear()
        self.assertEqual(self.logger.count(), 1)

    def test_get_recent_returns_copy(self):
        self.logger.log("INBOX", b"1", "err")
        recent = self.logger.get_recent(10)
        recent.clear()
        self.assertEqual(self.logger.count(), 1)

    def test_nonexistent_dir_is_created(self):
        """Logger should create the log directory if it doesn't exist."""
        nested_dir = os.path.join(self.test_dir, "a", "b", "c")
        logger = ErrorLogger(nested_dir)
        logger.log("INBOX", b"1", "test")
        self.assertTrue(os.path.exists(logger.log_path))


if __name__ == '__main__':
    unittest.main()
