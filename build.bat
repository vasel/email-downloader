python update_version.py
python -m PyInstaller --onefile --name email_downloader --add-binary "./dist/api-ms-win-core-path-l1-1-0.dll;." --version-file=file_version_info.txt email_downloader.py
pause
