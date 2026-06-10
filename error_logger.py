
import threading
import os
from datetime import datetime


class ErrorLogger:
    """
    Thread-safe error logger for email download failures.
    Maintains an in-memory list of errors and writes each entry to a log file on disk.
    """

    def __init__(self, log_dir: str, filename: str = "error_log.txt"):
        """
        Args:
            log_dir: Directory where the log file will be created.
            filename: Name of the log file.
        """
        self._entries = []
        self._lock = threading.Lock()
        self._log_dir = log_dir
        self._filename = filename
        self._log_path = os.path.join(log_dir, filename)

    @property
    def log_path(self) -> str:
        return self._log_path

    def log(self, folder: str, email_id, error_message: str):
        """
        Records an error entry. Thread-safe.

        Args:
            folder: The IMAP folder name.
            email_id: The email UID (bytes or str).
            error_message: Description of the error.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        uid_str = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
        entry = {
            "timestamp": timestamp,
            "folder": folder,
            "email_id": uid_str,
            "error": error_message,
        }
        line = f"[{timestamp}] Folder: {folder} | UID: {uid_str} | Error: {error_message}\n"

        with self._lock:
            self._entries.append(entry)
            self._write_line(line)

    def _write_line(self, line: str):
        """Appends a single line to the log file. Must be called under lock."""
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass  # Best-effort logging; don't crash the download

    def get_recent(self, n: int = 20):
        """Returns the last *n* error entries (list of dicts)."""
        with self._lock:
            return list(self._entries[-n:])

    def get_all(self):
        """Returns all error entries (list of dicts)."""
        with self._lock:
            return list(self._entries)

    def count(self) -> int:
        """Returns the total number of recorded errors."""
        with self._lock:
            return len(self._entries)

    def format_entry(self, entry: dict) -> str:
        """Formats a single entry dict into a human-readable string."""
        return (
            f"[{entry['timestamp']}] Folder: {entry['folder']} | "
            f"UID: {entry['email_id']} | Error: {entry['error']}"
        )
