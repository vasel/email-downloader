
import sys
import time
import msvcrt
import threading
from tqdm import tqdm


class DownloadSettings:
    """
    Shared mutable settings that can be changed via the interactive menu
    while the download is in progress.
    """

    def __init__(self, do_zip: bool = False, max_retries: int = 0):
        self.do_zip = do_zip
        self.max_retries = max_retries
        self.should_stop = False
        self.zip_configured = False  # True once user sets zip via menu

    def __repr__(self):
        return (
            f"DownloadSettings(do_zip={self.do_zip}, max_retries={self.max_retries}, "
            f"should_stop={self.should_stop}, zip_configured={self.zip_configured})"
        )


class InteractiveMenu:
    """
    Interactive menu shown during email download.
    Uses tqdm.write() so the progress bar is not disrupted.
    """

    MENU_TEXT = (
        "\n" + "=" * 50 + "\n"
        "  MENU\n"
        "=" * 50 + "\n"
        "  1 - Toggle ZIP creation at end\n"
        "  2 - Set number of error retries\n"
        "  3 - View live error log\n"
        "  4 - Stop processing (graceful)\n"
        "  0 - Close menu\n"
        "=" * 50
    )

    def __init__(self, settings: DownloadSettings, error_logger, shutdown_event: threading.Event):
        """
        Args:
            settings: Shared DownloadSettings instance.
            error_logger: ErrorLogger instance for live error viewing.
            shutdown_event: threading.Event to signal graceful shutdown.
        """
        self.settings = settings
        self.error_logger = error_logger
        self.shutdown_event = shutdown_event

    def show(self):
        """
        Displays the interactive menu and processes user selection.
        Blocks until the user closes the menu.
        """
        while True:
            zip_status = "YES" if self.settings.do_zip else "NO"
            tqdm.write(self.MENU_TEXT)
            tqdm.write(f"  Current ZIP setting: {zip_status}")
            tqdm.write(f"  Current retries: {self.settings.max_retries}")
            tqdm.write(f"  Errors so far: {self.error_logger.count()}")
            tqdm.write("")

            choice = self._read_menu_choice("Select option (0-4): ")

            if choice == "1":
                self._toggle_zip()
            elif choice == "2":
                self._set_retries()
            elif choice == "3":
                self._show_error_log()
            elif choice == "4":
                if self._confirm_stop():
                    break  # Exit menu after stopping
            elif choice == "0" or choice == "":
                tqdm.write("Menu closed.\n")
                break
            else:
                tqdm.write("Invalid option.\n")

    def _toggle_zip(self):
        """Toggles the ZIP setting."""
        self.settings.do_zip = not self.settings.do_zip
        self.settings.zip_configured = True
        status = "ENABLED" if self.settings.do_zip else "DISABLED"
        tqdm.write(f"\n  ZIP creation: {status}\n")

    def _set_retries(self):
        """Prompts the user to enter a new retry count."""
        tqdm.write(f"\n  Current retries: {self.settings.max_retries}")
        value = self._read_menu_choice("  Enter new retry count (number): ")
        try:
            n = int(value)
            if n < 0:
                tqdm.write("  Value must be >= 0.\n")
                return
            self.settings.max_retries = n
            tqdm.write(f"  Retries set to: {n}\n")
        except ValueError:
            tqdm.write("  Invalid number.\n")

    def _show_error_log(self):
        """Displays the most recent errors."""
        entries = self.error_logger.get_recent(20)
        if not entries:
            tqdm.write("\n  No errors recorded yet.\n")
            return

        tqdm.write(f"\n  === Last {len(entries)} error(s) ===")
        for entry in entries:
            tqdm.write(f"  {self.error_logger.format_entry(entry)}")
        tqdm.write(f"  Total errors: {self.error_logger.count()}")
        tqdm.write(f"  Full log: {self.error_logger.log_path}")
        tqdm.write("")

    def _confirm_stop(self) -> bool:
        """
        Asks user to confirm stopping. Default is NO (don't stop).
        Returns True if user confirmed stop.
        """
        tqdm.write("\n  WARNING: This will stop submitting new downloads.")
        tqdm.write("  Downloads already in progress will finish.")
        if self.settings.do_zip:
            tqdm.write("  ZIP will be created after remaining downloads complete.")
        choice = self._read_menu_choice("  Are you sure you want to stop? (y/N): ")

        if choice.lower() == "y":
            self.settings.should_stop = True
            self.shutdown_event.set()
            tqdm.write("  Graceful stop initiated. Waiting for active downloads...\n")
            return True
        else:
            tqdm.write("  Cancelled. Continuing download.\n")
            return False

    @staticmethod
    def _read_menu_choice(prompt: str) -> str:
        """
        Reads a line of input from the user using msvcrt (Windows).
        Echoes characters and returns on Enter.
        """
        sys.stdout.write(prompt)
        sys.stdout.flush()
        chars = []
        while True:
            if msvcrt.kbhit():
                char = msvcrt.getwche()
                if char in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(chars)
                elif char == "\x08":  # Backspace
                    if chars:
                        chars.pop()
                        sys.stdout.write(" \x08")
                        sys.stdout.flush()
                else:
                    chars.append(char)
            else:
                time.sleep(0.05)
