# IMAP Email Downloader

A robust, multi-threaded command-line tool to download emails from any IMAP server (Gmail, Outlook, etc.) and save them as `.eml` files. It features global deduplication, background scanning, and automatic ZIP archiving with SHA1 checksums.

## Features

*   **Multi-threaded Download**: High-speed downloading using concurrent threads.
*   **Hybrid Flow**: Immediately starts downloading the INBOX while scanning other folders in the background.
*   **Global Deduplication**: Uses `Message-ID` to prevent downloading the same email twice (e.g., from "All Mail" and "Inbox").
*   **Smart Resume**: Skips already downloaded emails in the current session.
*   **Robust Error Handling**: Automatically retries failed downloads and handles network timeouts.
*   **Interactive Progress**: Real-time progress bar with speed (emails/hour) and manual update trigger (Enter key).
*   **Auto-Archiving**: Automatically creates a ZIP archive of the downloaded emails and generates a SHA1 checksum file.
*   **Date Filtering**: Option to download emails from the last X days or a specific date range.

## Prerequisites

*   Python 3.6+
*   `pip` (Python package manager)

## Installation

1.  Clone this repository:
    ```bash
    git clone https://github.com/vasel/email-downloader.git
    cd email-downloader
    ```

2.  Install the required dependencies:
    ```bash
    pip install click tqdm
    ```

Alternatively, you can skip the installation and use the standalone executable located in the `dist` folder.

## Usage

Run the script using Python:

```bash
python email_downloader.py --email your_email@gmail.com --output-dir ./downloads
```

### Options

*   `--email`: **(Required)** Your full email address.
*   `--password`: Your email password. If omitted, you will be prompted securely.
    *   **Note for Gmail**: You **MUST** use an [App Password](https://myaccount.google.com/apppasswords) if 2FA is enabled.
*   `--output-dir`: Directory to save the downloaded emails (default: `downloaded_emails`).
*   `--days`: Download emails from the last X days (e.g., `--days 30`).
*   `--start-date`: Start date in `YYYY-MM-DD` format.
*   `--end-date`: End date in `YYYY-MM-DD` format.
*   `--threads`: Number of download threads (default: 10).
*   `--max-retries`: Number of auto-retries for failed downloads (default: 0).
*   `--batch`: Run in batch mode (no interactive prompts).
*   `--server`: IMAP server hostname (e.g., imap.gmail.com).
*   `--port`: IMAP server port (default: 993).
*   `--nossl`: Disable SSL (use for servers that do not support SSL).

### Examples

**Download all emails from the last 7 days:**
```bash
python email_downloader.py --email user@example.com --days 7 --output-dir ./my_emails
```

**Download emails from a specific date range:**
```bash
python email_downloader.py --email user@example.com --start-date 2023-01-01 --end-date 2023-12-31
```

## Output Structure

The tool creates a folder structure in your specified output directory:

```
output_dir/
├── user_domain_Start_End/          # Folder containing .eml files organized by folder (INBOX, Sent, etc.)
├── user_domain_Start_End.zip       # ZIP archive of the above folder
└── user_domain_Start_End.txt       # Checksum file containing SHA1 hash and stats
```

## Executables

To facilitate usage without installing Python, a compiled version is available:

*   **[Windows (All Versions)](dist/email_downloader.exe)**: Compatible with Windows 7, 10, and 11.

## Benchmark & Performance

The project includes a dedicated tool to test download performance and find the optimal number of threads for your connection and IMAP server.

### Usage

Run the `benchmark.py` script:

```bash
python benchmark.py --email your_email@gmail.com --days 3
```

The script will:
1.  Automatically test different thread counts (1, 2, 3, 5, 7, 10, 15, 20).
2.  Generate a detailed report in `benchmark_results.md`.
3.  Create a detailed execution log in `benchmark_detailed.log` for error diagnosis (e.g., "Too many connections").

### Benchmark Options

*   `--days`: Number of days to download (default: 3).
*   `--start-date` / `--end-date`: Specific date range.
*   `--output-dir`: Directory to save results (default: `benchmark_results`).

## License

MIT License
