
import click
import getpass
from datetime import datetime
from tqdm import tqdm
import os
import concurrent.futures
import webbrowser
import time
import msvcrt
import sys
import threading
from imap_client import AutoIMAPClient
from utils import ensure_directory, create_zip_archive, calculate_sha1, sanitize_filename

def timed_input(prompt, timeout=10, default='y'):
    """
    Waits for input with a timeout (Windows only using msvcrt).
    Returns the input character or default.
    """
    sys.stdout.write(f"{prompt} ")
    sys.stdout.flush()
    
    start_time = time.time()
    input_char = ''
    
    while True:
        if msvcrt.kbhit():
            char = msvcrt.getwche()
            if char == '\r' or char == '\n': # Enter pressed
                print()
                return default if not input_char else input_char
            input_char += char
            return input_char # Return immediately on first char for s/n
            
# Thread-local storage for IMAP connections
thread_local = threading.local()

def get_thread_client(email, password, server_address, port, use_ssl):
    """
    Returns a thread-local AutoIMAPClient, connecting if necessary.
    """
    if not hasattr(thread_local, 'client'):
        thread_local.client = AutoIMAPClient(email, password)
        thread_local.client.connection = None # Ensure clean state
    
    client = thread_local.client
    
    # Check if connected
    if not client.connection:
        if not client.connect(server_hostname=server_address, port=port, verbose=False, use_ssl=use_ssl):
            return None
    else:
        # Verify connection is still alive (noop)
        try:
            client.connection.noop()
        except Exception:
            # Reconnect
            try:
                client.close()
            except:
                pass
            if not client.connect(server_hostname=server_address, port=port, verbose=False, use_ssl=use_ssl):
                return None
                
    return client

def download_email_task(email, password, server_address, folder, email_id, output_dir, seen_ids=None, seen_lock=None, shutdown_event=None, port=993, use_ssl=True):
    """
    Worker function to download a single email.
    Returns (success, error_message).
    """
    try:
        if shutdown_event and shutdown_event.is_set():
            return False, "Shutdown initiated"

        # Use thread-local client
        client = get_thread_client(email, password, server_address, port, use_ssl)
        if not client:
            return False, "Connection failed"

        if shutdown_event and shutdown_event.is_set():
            # Do not close the shared connection here, just return
            return False, "Shutdown initiated"

        if not client.select_folder(folder):
            # Try reconnecting once if selection fails (maybe folder closed or connection dropped)
            try:
                client.close()
            except:
                pass
            if client.connect(server_hostname=server_address, port=port, verbose=False, use_ssl=use_ssl):
                 if not client.select_folder(folder):
                     return False, f"Failed to select folder {folder}"
            else:
                return False, "Connection lost during folder selection"

        # Deduplication Logic
        if seen_ids is not None and seen_lock is not None:
            msg_id = client.fetch_message_id(email_id)
            if msg_id:
                with seen_lock:
                    if msg_id in seen_ids:
                        # Do not close client
                        return True, "SKIPPED" # Treated as success but skipped
                    seen_ids.add(msg_id)
            # If no msg_id found, we proceed to download anyway to be safe
            
        if shutdown_event and shutdown_event.is_set():
            return False, "Shutdown initiated"

        content = client.fetch_email_content(email_id)
        # Do not close client
        
        if content:
            # Create folder-specific subdirectory
            # Remove INBOX. or INBOX/ prefix for cleaner folder names
            # But keep "INBOX" as is.
            display_folder = folder
            upper_folder = display_folder.upper()
            
            if upper_folder.startswith("INBOX.") or upper_folder.startswith("INBOX/"):
                display_folder = display_folder[6:]
            
            folder_safe = sanitize_filename(display_folder)
            folder_path = os.path.join(output_dir, folder_safe)
            ensure_directory(folder_path)
            
            # Save file
            filename = f"email_{folder_safe}_{email_id.decode()}.eml"
            file_path = os.path.join(folder_path, filename)
            
            with open(file_path, 'wb') as f:
                f.write(content)
            return True, None
        else:
            return False, f"Empty content (UID: {email_id.decode()})"
    except Exception as e:
        # In case of error, we might want to invalidate the connection for next time
        if hasattr(thread_local, 'client'):
             try:
                 thread_local.client.close()
             except:
                 pass
             thread_local.client.connection = None
        return False, str(e)

@click.command()
@click.option('--email', help='Your email address')
@click.option('--password', help='Your email password (or App Password). If not provided, will prompt securely.')
@click.option('--start-date', help='Start date (YYYY-MM-DD)', default=None)
@click.option('--end-date', help='End date (YYYY-MM-DD)', default=None)
@click.option('--days', help='Download emails from the last X days', type=int, default=None)
@click.option('--output-dir', default='downloaded_emails', help='Directory to save emails')
@click.option('--threads', default=10, help='Number of threads for downloading')
@click.option('--max-retries', default=0, help='Number of auto-retries for failed downloads', type=int)
@click.option('--batch', is_flag=True, help='Run in batch mode (no interactive prompts, defaults to No for optional steps)')
@click.option('--server', help='IMAP server hostname (e.g. imap.gmail.com)')
@click.option('--port', default=993, help='IMAP server port', type=int)
@click.option('--nossl', is_flag=True, help='Disable SSL (use for servers that do not support SSL)')
@click.option('--zip-only', help='Only zip and hash this directory (skip download)', default=None)
@click.option('--compression-level', default=0, help='Compression level (0=Store/No Compression, 1-9=Deflate)', type=int)
def main(email, password, start_date, end_date, days, output_dir, threads, max_retries, batch, server, port, nossl, zip_only, compression_level):
    """
    Downloads emails from an IMAP server with auto-discovery and multi-threading.
    """
    import zipfile
    
    # Determine compression settings
    # Default is STORED (0)
    if compression_level == 0:
        compression_method = zipfile.ZIP_STORED
        compress_lvl_arg = None
    else:
        compression_method = zipfile.ZIP_DEFLATED
        compress_lvl_arg = compression_level

    # --- ZIP ONLY MODE ---
    if zip_only:
        target_path = os.path.abspath(zip_only)
        if not os.path.isdir(target_path):
             # Try joining with output_dir if not absolute or existing
             possible_path = os.path.join(output_dir, zip_only)
             if os.path.isdir(possible_path):
                 target_path = possible_path
             else:
                 click.echo(f"Error: Directory not found: {zip_only}")
                 return

        base_name = os.path.basename(target_path)
        if not base_name: # Handle trailing slash
             base_name = os.path.basename(os.path.dirname(target_path))
             
        # Output zip to the PARENT of the target folders, or just output_dir?
        # Let's stick to output_dir to be safe, or just next to the folder if it's external.
        # Use output_dir as destination for zip if provided, else parent of target.
        if output_dir == 'downloaded_emails' and not os.path.exists('downloaded_emails'):
             # If default output dir doesn't exist, maybe user didn't mean to use it.
             # Saving next to folder.
             dest_dir = os.path.dirname(target_path)
        else:
             dest_dir = output_dir
             ensure_directory(dest_dir)

        zip_filename = f"{base_name}.zip"
        zip_path = os.path.join(dest_dir, zip_filename)
        
        click.echo(f"Zipping folder: {target_path}")
        click.echo(f"Destination: {zip_path}")
        if compression_level == 0:
             click.echo("Compression: None (Store)")
        else:
             click.echo(f"Compression: Deflated (Level {compression_level})")
        
        create_zip_archive(target_path, zip_path, compression_method=compression_method, compress_level=compress_lvl_arg)
        
        click.echo("Calculating SHA1 hash...")
        sha1_hash = calculate_sha1(zip_path)
        file_size = os.path.getsize(zip_path)
        
        click.echo(f"SHA1 Hash: {sha1_hash}")
        
        # Save hash
        checksum_file = os.path.join(dest_dir, f"{base_name}.txt")
        with open(checksum_file, "w") as f:
            f.write(f"File: {zip_filename}\n")
            f.write(f"Size: {file_size} bytes\n")
            f.write(f"SHA1: {sha1_hash}\n")
            f.write(f"Date: {datetime.now().isoformat()}\n")
            f.write("Mode: Zip Only\n")
            
        click.echo(f"Integrity info saved in {checksum_file}")
        return

    # Normal Mode requirements
    if not email:
        email = click.prompt('Email address')
    
    use_ssl = not nossl
    if not password:
        password = getpass.getpass("Password (hidden): ")

    # Parse dates
    s_date = None
    e_date = None
    
    if days and start_date:
        click.echo("Error: You cannot use --days and --start-date simultaneously.")
        return

    try:
        if days:
            from datetime import timedelta
            s_date = datetime.now() - timedelta(days=days)
            s_date = s_date.replace(hour=0, minute=0, second=0, microsecond=0)
            click.echo(f"Downloading emails since: {s_date.strftime('%Y-%m-%d')} (last {days} days)")
        elif start_date:
            s_date = datetime.strptime(start_date, '%Y-%m-%d')
            
        if end_date:
            e_date = datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError:
        click.echo("Error: Invalid date format. Use YYYY-MM-DD.")
        return

    # Initial connection to discover server and get IDs
    client = AutoIMAPClient(email, password)
    
    click.echo(f"Connecting to {email}...")
    
    # Connection Loop with Password Retry
    while True:
        if client.connect(server_hostname=server, port=port, verbose=True, use_ssl=use_ssl):
            break
        
        click.echo("Error: Could not connect or auto-discover IMAP server.")
        
        # UX Improvement: Gmail App Password (only show once or if relevant)
        if 'gmail.com' in email.lower() or 'googlemail.com' in email.lower():
            click.echo("\n" + "="*60)
            click.echo("GMAIL ALERT: Authentication failed.")
            click.echo("To use this software with Gmail, you MUST use an 'App Password'.")
            click.echo("Visit: https://myaccount.google.com/apppasswords")
            click.echo("Your normal Google password will NOT work.")
            click.echo("="*60 + "\n")

        # Fallback: Ask for new password
        new_password = getpass.getpass("Authentication failed or server not found. Enter new password to retry (or press Enter to exit): ")
        if new_password:
            client.password = new_password
            password = new_password # Update local var too if needed elsewhere
            # Retry loop
        else:
            return
    
    # Store the discovered server address to pass to threads
    server_address = client.server_address
    click.echo(f"Identified server: {server_address}")

    try:
        # List folders
        click.echo("Listing folders...")
        folders = client.list_folders()
        
        # Find Inbox
        inbox_folder = None
        other_folders = []
        
        for f in folders:
            if f.lower() == 'inbox':
                inbox_folder = f
            else:
                other_folders.append(f)
        
        client.close() # Close main connection

        ensure_directory(output_dir)
        
        click.echo(f"Starting download with {threads} threads...")
        click.echo("Mode: Immediate Inbox + Background Scan")
        
        # Deduplication globals
        seen_ids = set()
        seen_lock = threading.Lock()
        count_lock = threading.Lock()
        shutdown_event = threading.Event()
        
        downloaded_count = 0
        skipped_count = 0
        failed_tasks = [] # List of (folder, email_id)
        status = "Completed"
        
        # Folder stats tracking: {folder_name: {'downloaded': 0, 'skipped': 0, 'failed': 0}}
        folder_stats = {}
        folder_stats_lock = threading.Lock()

        # Active threads tracking
        active_threads = 0
        active_threads_lock = threading.Lock()
        
        # Executors
        # Scan executor: 1 thread for background scan
        scan_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        # Download executor: N threads
        download_executor = concurrent.futures.ThreadPoolExecutor(max_workers=threads)
        
        download_futures = []
        
        # Progress bar
        pbar = tqdm(total=0, unit=' emails', dynamic_ncols=True)
        
        start_time = time.time()
        
        def update_speed():
            elapsed = time.time() - start_time
            if elapsed > 0:
                speed_h = (downloaded_count / elapsed) * 3600
                with active_threads_lock:
                    current_threads = active_threads
                pbar.set_postfix_str(f"{speed_h:.0f} emails/h | Active: {current_threads} | Skipped: {skipped_count} | Errors: {len(failed_tasks)}")

        def download_done_callback(future):
            nonlocal downloaded_count, skipped_count
            # Check if already handled (e.g. by timeout logic)
            if getattr(future, 'handled', False):
                return

            folder, eid = getattr(future, 'task_info', ("Unknown", b"0"))
            
            try:
                success, error_msg, _, _ = future.result()
                with count_lock:
                    if getattr(future, 'handled', False): return
                    future.handled = True
                    
                    if success:
                        if error_msg == "SKIPPED":
                            skipped_count += 1
                            with folder_stats_lock:
                                if folder not in folder_stats: folder_stats[folder] = {'downloaded': 0, 'skipped': 0, 'failed': 0}
                                folder_stats[folder]['skipped'] += 1
                        else:
                            downloaded_count += 1
                            with folder_stats_lock:
                                if folder not in folder_stats: folder_stats[folder] = {'downloaded': 0, 'skipped': 0, 'failed': 0}
                                folder_stats[folder]['downloaded'] += 1
                    else:
                        failed_tasks.append((folder, eid))
                        with folder_stats_lock:
                            if folder not in folder_stats: folder_stats[folder] = {'downloaded': 0, 'skipped': 0, 'failed': 0}
                            folder_stats[folder]['failed'] += 1
                    
                    pbar.update(1)
                    # REMOVED: update_speed() call to reduce I/O contention
            except Exception:
                with count_lock:
                    if getattr(future, 'handled', False): return
                    future.handled = True
                    failed_tasks.append((folder, eid))
                    with folder_stats_lock:
                        if folder not in folder_stats: folder_stats[folder] = {'downloaded': 0, 'skipped': 0, 'failed': 0}
                        folder_stats[folder]['failed'] += 1
                    pbar.update(1)

        # Generate dynamic filename base upfront
        # Format: emailuser_domain_Start_End
        email_parts = email.split('@')
        if len(email_parts) > 1:
            email_user = f"{email_parts[0]}_{email_parts[1]}"
        else:
            email_user = email_parts[0]
        
        date_str = ""
        if s_date:
            date_str += f"_{s_date.strftime('%Y%m%d')}"
        else:
            date_str += "_Start"
            
        if e_date:
            date_str += f"_{e_date.strftime('%Y%m%d')}"
        else:
            date_str += f"_{datetime.now().strftime('%Y%m%d')}"
            
        base_name = f"{email_user}{date_str}"
        final_subfolder_path = os.path.join(output_dir, base_name)
        
        click.echo(f"Saving emails to: {final_subfolder_path}")
        ensure_directory(final_subfolder_path)

        # Wrapper to track failures since callback doesn't have context easily
        def download_wrapper(em, pw, srv, f, eid, out, s_ids, s_lock, s_event, port, use_ssl):
            nonlocal active_threads
            with active_threads_lock:
                active_threads += 1
            try:
                if s_event.is_set():
                    return False, "Shutdown initiated", f, eid
                res = download_email_task(em, pw, srv, f, eid, out, s_ids, s_lock, s_event, port, use_ssl)
                if not res[0]:
                    return False, res[1], f, eid
                return True, res[1], f, eid
            finally:
                with active_threads_lock:
                    active_threads -= 1

        def submit_download(folder, eid):
            if shutdown_event.is_set():
                return None
            try:
                # Use final_subfolder_path directly
                f = download_executor.submit(download_wrapper, email, password, server_address, folder, eid, final_subfolder_path, seen_ids, seen_lock, shutdown_event, port, use_ssl)
                f.task_info = (folder, eid) # Attach info for timeout handling
                f.add_done_callback(download_done_callback)
                download_futures.append(f)
                return f
            except RuntimeError:
                # Executor likely shutdown
                return None

        try:
            # 1. Scan & Download Inbox IMMEDIATELY
            if inbox_folder:
                click.echo(f"Scanning {inbox_folder}...")
                c = AutoIMAPClient(email, password)
                if c.connect(server_hostname=server_address, port=port, verbose=False, use_ssl=use_ssl):
                    ids = c.fetch_email_ids(inbox_folder, s_date, e_date)
                    c.close()
                    count = len(ids)
                    if count > 0:
                        pbar.total += count
                        pbar.refresh()
                        for eid in ids:
                            if shutdown_event.is_set(): break
                            submit_download(inbox_folder, eid)
            
            # 2. Background Scan for others
            def background_scan():
                # Use a separate client for scanning to avoid conflict
                scan_client = AutoIMAPClient(email, password)
                if not scan_client.connect(server_hostname=server_address, port=port, verbose=False, use_ssl=use_ssl):
                    tqdm.write("Error: Background scanner could not connect.")
                    return

                for folder in other_folders:
                    if shutdown_event.is_set(): break
                    try:
                        # Update status to show what we are scanning
                        # We can't easily update pbar description from here without lock, 
                        # so we use tqdm.write for log and maybe a shared status string
                        tqdm.write(f"Scanning folder: {folder}...")
                        
                        # Select folder
                        if not scan_client.select_folder(folder):
                            tqdm.write(f"Skipping {folder}: Could not select.")
                            continue
                            
                        ids = scan_client.fetch_email_ids(folder, s_date, e_date)
                        
                        if ids:
                            count = len(ids)
                            tqdm.write(f"-> Found {count} emails in {folder}")
                            
                            # Update total safely
                            with count_lock:
                                pbar.total += count
                                pbar.refresh()
                                
                            for eid in ids:
                                if shutdown_event.is_set(): break
                                submit_download(folder, eid)
                        else:
                            tqdm.write(f"-> No emails in {folder}")
                             
                    except Exception as e:
                        tqdm.write(f"Error scanning {folder}: {e}")
                
                scan_client.close()
                tqdm.write("Background scan completed.")
            
            scan_future = scan_executor.submit(background_scan)
            
            # 3. Interactive Wait Loop
            # Wait until scan is done AND all downloads are done
            click.echo("\nPress ENTER to force progress update...")
            
            last_update_time = time.time()
            
            while True:
                # Check if scan is done
                scan_done = scan_future.done()
                
                # Check if all downloads are done
                # Optimization: Only check if scan is done, otherwise we know we aren't done
                if scan_done:
                    downloads_done = all(f.done() for f in download_futures)
                    if downloads_done:
                        break
                
                # Check for user input (Enter to update)
                if msvcrt.kbhit():
                    char = msvcrt.getwche()
                    if char == '\r' or char == '\n':
                        # Force update
                        with count_lock:
                            pbar.refresh()
                            # Print explicit status line below pbar
                            tqdm.write(f"\n[Status Update] Downloaded: {downloaded_count} | Skipped: {skipped_count} | Remaining: {pbar.total - (downloaded_count + skipped_count + len(failed_tasks))}")
                
                # Periodic Update (every 0.5s)
                current_time = time.time()
                if current_time - last_update_time > 0.5:
                    update_speed()
                    last_update_time = current_time
                
                # Sleep to prevent CPU hogging
                time.sleep(0.1)
            
            # Final check for any exceptions/timeouts not caught
            for f in download_futures:
                try:
                    f.result(timeout=0) # Should be done
                except Exception:
                    pass # Handled by callback or ignored
                
        except KeyboardInterrupt:
            pbar.close()
            click.echo("\n\nCancellation requested (Ctrl+C).")
            click.echo("Stopping background threads... please wait.")
            shutdown_event.set()
            scan_executor.shutdown(wait=False, cancel_futures=True)
            download_executor.shutdown(wait=False, cancel_futures=True)
            status = "Cancelled"
        finally:
            pbar.close()
            scan_executor.shutdown(wait=False)
            download_executor.shutdown(wait=False)
            
        # Retry Logic
        # Retry Logic
        retry_attempt = 0
        
        while failed_tasks and status == "Completed":
            click.echo(f"\n{len(failed_tasks)} emails failed.")
            
            # Determine if we should auto-retry or ask user
            should_retry = False
            timeout_val = 60 # Base timeout
            
            if retry_attempt < max_retries:
                click.echo(f"Auto-retry attempt {retry_attempt + 1}/{max_retries}...")
                should_retry = True
                # Exponential backoff for timeout (60, 120, 180...)
                timeout_val = 60 * (retry_attempt + 1)
                retry_attempt += 1
            else:
                # Manual intervention
                if batch:
                    choice = 'n'
                else:
                    # If we exhausted auto-retries, default is 'n', else 'y'
                    default_choice = 'n' if max_retries > 0 else 'y'
                    choice = timed_input(f"Do you want to retry downloading the {len(failed_tasks)} errors? (y/n) [10s]:", timeout=10, default=default_choice)
                
                if choice.lower() == 'y':
                    should_retry = True
                    # Reset attempt count if user manually says yes, to allow further manual retries? 
                    # Or just keep increasing timeout? Let's keep increasing timeout but cap it maybe?
                    # For simplicity, let's just use base timeout or current level.
                    timeout_val = 60 * (retry_attempt + 1)
                else:
                    should_retry = False

            if should_retry:
                click.echo(f"Retrying failures with timeout {timeout_val}s...")
                # Retry batch
                new_failed = []
                
                # We need a new list of futures for retry
                retry_futures = []
                
                # Helper for retry callback
                def retry_done_callback(future):
                    folder, eid = getattr(future, 'task_info', ("Unknown", b"0"))
                    try:
                        success, error_msg, _, _ = future.result()
                        if not success:
                             new_failed.append((folder, eid))
                    except:
                        new_failed.append((folder, eid))
                    pbar_retry.update(1)

                with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
                    with tqdm(total=len(failed_tasks), unit=' emails') as pbar_retry:
                        for folder, eid in failed_tasks:
                            # Use final_subfolder_path here as well
                            f = executor.submit(download_wrapper, email, password, server_address, folder, eid, final_subfolder_path, seen_ids, seen_lock, shutdown_event, port, use_ssl)
                            f.task_info = (folder, eid)
                            f.add_done_callback(retry_done_callback)
                            retry_futures.append(f)
                        
                        # Wait for retries
                        for f in retry_futures:
                            try:
                                f.result(timeout=timeout_val)
                            except:
                                pass
                            
                recovered = len(failed_tasks) - len(new_failed)
                click.echo(f"Recovered: {recovered}. Still failing: {len(new_failed)}")
                failed_tasks = new_failed
                
                # Update total downloaded count
                downloaded_count += recovered
                
                # If manual retry was triggered and we are here, loop continues.
                # If auto-retry was triggered, loop continues.
            else:
                break

        end_time = time.time()
        duration_seconds = end_time - start_time
        duration_hours = duration_seconds / 3600.0
        emails_per_hour = downloaded_count / duration_hours if duration_hours > 0 else 0
        
        total_items = pbar.total if pbar.total else 0
        processed_count = downloaded_count + skipped_count + len(failed_tasks)
        remaining_count = max(0, total_items - processed_count)

        click.echo(f"\nDownload finished. Status: {status}")
        click.echo(f"Downloaded: {downloaded_count}")
        click.echo(f"Skipped (Duplicates): {skipped_count}")
        click.echo(f"Final Errors: {len(failed_tasks)}")
        click.echo(f"Remaining (Cancelled): {remaining_count}")
        click.echo(f"Average Speed: {emails_per_hour:.2f} emails/hour")
        click.echo(f"Emails saved in: {os.path.abspath(output_dir)}")
        
        # Zip and Hash section with Timeout
        click.echo("\n")
        if batch:
            user_choice = 'n'
        else:
            user_choice = timed_input("Do you want to create a ZIP archive of the downloaded emails? (y/n) [10s]:", timeout=10, default='y')
        
        if user_choice.lower() == 'y':
            zip_filename = f"{base_name}.zip"
            zip_path = os.path.join(output_dir, zip_filename)
            
            click.echo(f"Creating ZIP archive: {zip_path}...")
            
            # Zip the subfolder
            create_zip_archive(final_subfolder_path, zip_path, compression_method=compression_method, compress_level=compress_lvl_arg)
            
            click.echo("Calculating SHA1 hash...")
            sha1_hash = calculate_sha1(zip_path)
            file_size = os.path.getsize(zip_path)
            
            click.echo(f"SHA1 Hash: {sha1_hash}")
            
            # Save hash to file
            checksum_file = os.path.join(output_dir, f"{base_name}.txt")
            with open(checksum_file, "w") as f:
                f.write(f"File: {zip_filename}\n")
                f.write(f"Size: {file_size} bytes\n")
                f.write(f"SHA1: {sha1_hash}\n")
                f.write(f"Date: {datetime.now().isoformat()}\n")
                f.write(f"Status: {status}\n")
                f.write(f"Total Emails: {total_items}\n")
                f.write(f"Downloaded: {downloaded_count}\n")
                f.write(f"Skipped: {skipped_count}\n")
                f.write(f"Failed: {len(failed_tasks)}\n")
                f.write(f"Remaining: {remaining_count}\n")
                f.write(f"Speed: {emails_per_hour:.2f} emails/hour\n")
                f.write(f"Server Connected: {server_address}\n")
                if hasattr(client, 'connection_attempts') and client.connection_attempts:
                    f.write("Failed Connection Attempts:\n")
                    for srv, err in client.connection_attempts:
                        f.write(f"  - {srv}: {err}\n")
                f.write("\n--- Folder Statistics ---\n")
                for folder, stats in folder_stats.items():
                    f.write(f"Folder: {folder} - Downloaded: {stats['downloaded']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}\n")
            
            click.echo(f"Integrity info saved in {checksum_file}")

    except Exception as e:
        click.echo(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()
        if 'client' in locals() and client.connection:
            try:
                client.close()
            except:
                pass

if __name__ == '__main__':
    main()
