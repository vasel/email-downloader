import re
import os
import zipfile
import hashlib
import threading
import concurrent.futures
import queue
from tqdm import tqdm

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

def create_zip_archive(source_dir: str, output_filename: str, compression_method=zipfile.ZIP_STORED, compress_level=None):
    """
    Zips the contents of source_dir into output_filename using multi-threading for reading
    and a progress bar.
    """
    # 1. Collect all files to zip
    file_list = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            file_path = os.path.join(root, file)
            arcname = os.path.relpath(file_path, start=source_dir)
            file_list.append((file_path, arcname))

    total_files = len(file_list)
    
    # 2. Define a worker to read file content
    def read_file(path_info):
        f_path, arc_name = path_info
        try:
            with open(f_path, 'rb') as f:
                data = f.read()
            return arc_name, data, None
        except Exception as e:
            return arc_name, None, e

    # 3. Use ThreadPoolExecutor to read files in parallel
    max_workers = os.cpu_count() 
    
    # Re-implementing with as_completed to avoid memory spike and allow streaming write
    # Setup compression args
    kwargs = {}
    if compression_method == zipfile.ZIP_DEFLATED and compress_level is not None:
        # compresslevel was added in Python 3.7
        kwargs['compresslevel'] = compress_level
        
    with zipfile.ZipFile(output_filename, 'w', compression_method, **kwargs) as zipf:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {executor.submit(read_file, f): f for f in file_list}
            
            for future in tqdm(concurrent.futures.as_completed(future_to_file), total=total_files, unit=' files', desc="Zipping"):
                arcname, data, error = future.result()
                if error:
                    print(f"Error reading {arcname}: {error}")
                else:
                    zipf.writestr(arcname, data)

def calculate_sha1(filename: str) -> str:
    """
    Calculates the SHA1 hash of a file using a producer-consumer model for read-ahead buffering.
    """
    sha1 = hashlib.sha1()
    file_size = os.path.getsize(filename)
    chunk_size = 1024 * 1024 * 4 # 4MB chunks
    
    q = queue.Queue(maxsize=5) # Buffer a few chunks ahead
    
    def producer():
        try:
            with open(filename, 'rb') as f:
                while True:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    q.put(data)
        except Exception as e:
            print(f"Error reading file for hash: {e}")
        finally:
            q.put(None) # Sentinel

    t = threading.Thread(target=producer)
    t.start()
    
    with tqdm(total=file_size, unit='B', unit_scale=True, unit_divisor=1024, desc="Hashing") as pbar:
        while True:
            data = q.get()
            if data is None:
                break
            sha1.update(data)
            pbar.update(len(data))
            
    t.join()
    return sha1.hexdigest()
