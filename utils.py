import re
import os
import zipfile
import hashlib

def sanitize_filename(filename: str) -> str:
    """
    Removes illegal characters from filenames.
    """
    # Keep only alphanumeric, dots, dashes and underscores
    return re.sub(r'[^\w\-\.]', '_', filename)

def ensure_directory(path: str):
    """
    Ensures the directory exists.
    """
    if not os.path.exists(path):
        os.makedirs(path)

def create_zip_archive(source_dir: str, output_filename: str):
    """
    Zips the contents of source_dir into output_filename.
    """
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, start=source_dir)
                zipf.write(file_path, arcname)

def calculate_sha1(filename: str) -> str:
    """
    Calculates the SHA1 hash of a file.
    """
    sha1 = hashlib.sha1()
    with open(filename, 'rb') as f:
        while True:
            data = f.read(65536) # 64kb chunks
            if not data:
                break
            sha1.update(data)
    return sha1.hexdigest()
