import click
import getpass
from datetime import datetime
from tqdm import tqdm
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
            
        if time.time() - start_time > timeout:
            print(f"\nTimeout! Defaulting to: {default}")
            return default
        
        time.sleep(0.1)

def download_email_task(email, password, server_address, folder, email_id, output_dir, seen_ids=None, seen_lock=None):
    """
    Worker function to download a single email.
    Returns (success, error_message).
    """
    try:
        client = AutoIMAPClient(email, password)
        if not client.connect(server_hostname=server_address, verbose=False):
            return False, "Connection failed"

        if not client.select_folder(folder):
            client.close()
            return False, f"Failed to select folder {folder}"

        # Deduplication Logic
        if seen_ids is not None and seen_lock is not None:
            msg_id = client.fetch_message_id(email_id)
            if msg_id:
                with seen_lock:
                    if msg_id in seen_ids:
                        client.close()
                        return True, None # Treated as success (skipped)
                    seen_ids.add(msg_id)
            # If no msg_id found, we proceed to download anyway to be safe

        content = client.fetch_email_content(email_id)
        client.close()

        if content:
            # Create folder-specific subdirectory
            folder_safe = "".join([c if c.isalnum() or c in (' ', '-', '_') else '_' for c in folder])
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
        return False, str(e)

@click.command()
@click.option('--email', prompt='Email address', help='Your email address')
@click.option('--password', help='Your email password (or App Password). If not provided, will prompt securely.')
@click.option('--start-date', help='Start date (YYYY-MM-DD)', default=None)
@click.option('--end-date', help='End date (YYYY-MM-DD)', default=None)
@click.option('--days', help='Download emails from the last X days', type=int, default=None)
@click.option('--output-dir', default='downloaded_emails', help='Directory to save emails')
@click.option('--threads', default=10, help='Number of threads for downloading')
def main(email, password, start_date, end_date, days, output_dir, threads):
    """
    Downloads emails from an IMAP server with auto-discovery and multi-threading.
    """
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
    if not client.connect(verbose=True):
        click.echo("Error: Could not connect or auto-discover IMAP server.")
        
        # UX Improvement: Gmail App Password
        if 'gmail.com' in email.lower() or 'googlemail.com' in email.lower():
            click.echo("\n" + "="*60)
            click.echo("GMAIL ALERT: Authentication failed.")
            click.echo("To use this software with Gmail, you MUST use an 'App Password'.")
            click.echo("Your normal Google password will NOT work.")
            click.echo("Opening instructions in browser...")
            click.echo("="*60 + "\n")
            try:
                webbrowser.open('https://myaccount.google.com/apppasswords')
            except:
                click.echo("Visit: https://myaccount.google.com/apppasswords")
        
        # Fallback Manual Input
        server_input = input("Do you want to enter the server manually? (Type address or Enter to exit): ").strip()
        if server_input:
            if not client.connect(server_hostname=server_input, verbose=True):
                click.echo("Failed to connect to the provided server.")
                return
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
        
        downloaded_count = 0
        failed_tasks = [] # List of (folder, email_id)
        status = "Completed"
        
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
                pbar.set_postfix_str(f"{speed_h:.0f} emails/h | Errors: {len(failed_tasks)}")

        def download_done_callback(future):
            nonlocal downloaded_count
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
                        downloaded_count += 1
                    else:
                        failed_tasks.append((folder, eid))
                    
                    pbar.update(1)
                    # REMOVED: update_speed() call to reduce I/O contention
            except Exception:
                with count_lock:
                    if getattr(future, 'handled', False): return
                    future.handled = True
                    failed_tasks.append((folder, eid))
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
        def download_wrapper(em, pw, srv, f, eid, out, s_ids, s_lock):
            res = download_email_task(em, pw, srv, f, eid, out, s_ids, s_lock)
            if not res[0]:
                return False, res[1], f, eid
            return True, None, f, eid

        def submit_download(folder, eid):
            # Use final_subfolder_path directly
            f = download_executor.submit(download_wrapper, email, password, server_address, folder, eid, final_subfolder_path, seen_ids, seen_lock)
            f.task_info = (folder, eid) # Attach info for timeout handling
            f.add_done_callback(download_done_callback)
            download_futures.append(f)
            return f

        try:
            # 1. Scan & Download Inbox IMMEDIATELY
            if inbox_folder:
                click.echo(f"Scanning {inbox_folder}...")
                c = AutoIMAPClient(email, password)
                if c.connect(server_hostname=server_address, verbose=False):
                    ids = c.fetch_email_ids(inbox_folder, s_date, e_date)
                    c.close()
                    count = len(ids)
                    if count > 0:
                        pbar.total += count
                        pbar.refresh()
                        for eid in ids:
                            submit_download(inbox_folder, eid)
            
            # 2. Background Scan for others
            def background_scan():
                for folder in other_folders:
                    try:
                        c = AutoIMAPClient(email, password)
                        if not c.connect(server_hostname=server_address, verbose=False):
                            continue
                        ids = c.fetch_email_ids(folder, s_date, e_date)
                        c.close()
                        if ids:
                            count = len(ids)
                            # Update total safely
                            with count_lock:
                                pbar.total += count
                                pbar.refresh()
                            for eid in ids:
                                submit_download(folder, eid)
                    except:
                        pass
            
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
                            tqdm.write(f"\n[Status Update] Downloaded: {downloaded_count}/{pbar.total} | Failed: {len(failed_tasks)}")
                
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
            click.echo("\n\nCancellation requested (Ctrl+C).")
            scan_executor.shutdown(wait=False, cancel_futures=True)
            download_executor.shutdown(wait=False, cancel_futures=True)
            if click.confirm("Do you really want to stop?", default=True):
                status = "Cancelled"
            else:
                status = "Cancelled (Aborted)"
        finally:
            pbar.close()
            scan_executor.shutdown(wait=False)
            download_executor.shutdown(wait=False)
            
        # Retry Logic
        while failed_tasks and status == "Completed":
            click.echo(f"\n{len(failed_tasks)} emails failed.")
            choice = timed_input(f"Do you want to retry downloading the {len(failed_tasks)} errors? (y/n) [10s]:", timeout=10, default='y')
            
            if choice.lower() == 'y':
                click.echo("Retrying failures...")
                # Retry batch
                new_failed = []
                # Reset pbar for retry
                
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
                            f = executor.submit(download_wrapper, email, password, server_address, folder, eid, final_subfolder_path, seen_ids, seen_lock)
                            f.task_info = (folder, eid)
                            f.add_done_callback(retry_done_callback)
                            retry_futures.append(f)
                        
                        # Wait for retries
                        for f in retry_futures:
                            try:
                                f.result(timeout=60)
                            except:
                                pass
                            
                recovered = len(failed_tasks) - len(new_failed)
                click.echo(f"Recovered: {recovered}. Still failing: {len(new_failed)}")
                failed_tasks = new_failed
                
                # Update total downloaded count
                downloaded_count += recovered
            else:
                break

        end_time = time.time()
        duration_seconds = end_time - start_time
        duration_hours = duration_seconds / 3600.0
        emails_per_hour = downloaded_count / duration_hours if duration_hours > 0 else 0
        
        click.echo(f"\nDownload finished. Status: {status}")
        click.echo(f"Downloaded: {downloaded_count}/{pbar.total if pbar.total else 0}")
        click.echo(f"Final Errors: {len(failed_tasks)}")
        click.echo(f"Average Speed: {emails_per_hour:.2f} emails/hour")
        click.echo(f"Emails saved in: {os.path.abspath(output_dir)}")
        
        # Zip and Hash section with Timeout
        click.echo("\n")
        user_choice = timed_input("Do you want to create a ZIP archive of the downloaded emails? (y/n) [10s]:", timeout=10, default='y')
        
        if user_choice.lower() == 'y':
            zip_filename = f"{base_name}.zip"
            zip_path = os.path.join(output_dir, zip_filename)
            
            click.echo(f"Creating ZIP archive: {zip_path}...")
            
            # Zip the subfolder
            create_zip_archive(final_subfolder_path, zip_path)
            
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
                f.write(f"Total Emails: {pbar.total if pbar.total else 0}\n")
                f.write(f"Downloaded: {downloaded_count}\n")
                f.write(f"Failed: {len(failed_tasks)}\n")
                f.write(f"Speed: {emails_per_hour:.2f} emails/hour\n")
            
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
