import subprocess
import time
import re
import os
import getpass
import click
from datetime import datetime

@click.command()
@click.option('--email', prompt='Email address', help='Your email address')
@click.option('--password', help='Your email password (or App Password).')
@click.option('--days', help='Download emails from the last X days', type=int, default=None)
@click.option('--start-date', help='Start date (YYYY-MM-DD)', default=None)
@click.option('--end-date', help='End date (YYYY-MM-DD)', default=None)
@click.option('--output-dir', default='benchmark_results', help='Directory to save downloaded emails (subfolders will be created)')
def benchmark(email, password, days, start_date, end_date, output_dir):
    """
    Runs email_downloader.py with different thread counts to find the optimal setting.
    """
    if not password:
        password = getpass.getpass("Password (hidden): ")

    # Default to 3 days if nothing specified, to match previous behavior or safe default
    if not days and not start_date:
        days = 3

    thread_counts = [1, 2, 3, 5,7,8,9,10,11,12,13,14,15,17,19,20]
    results = []
    
    log_file = "benchmark_detailed.log"
    with open(log_file, "w") as f:
        f.write(f"Benchmark Started: {datetime.now().isoformat()}\n")
        f.write("-" * 80 + "\n")

    print(f"Starting benchmark for {email}")
    if days: print(f"Mode: Last {days} days")
    if start_date: print(f"Mode: Since {start_date}")
    print(f"Testing thread counts: {thread_counts}")
    print(f"Detailed log: {os.path.abspath(log_file)}")
    print("-" * 60)

    def format_time(seconds):
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

    for threads in thread_counts:
        print(f"\nRunning with {threads} threads...")
        
        run_output_dir = os.path.join(output_dir, f"run_threads_{threads}")
        
        cmd = [
            "python", "email_downloader.py",
            "--email", email,
            "--password", password,
            "--output-dir", run_output_dir,
            "--threads", str(threads),
            "--batch",
            "--max-retries", "0"
        ]
        
        if days:
            cmd.extend(["--days", str(days)])
        if start_date:
            cmd.extend(["--start-date", start_date])
        if end_date:
            cmd.extend(["--end-date", end_date])
        
        start_time = time.time()
        full_output = ""
        
        # Log run start
        with open(log_file, "a") as f:
            f.write(f"\n{'='*30}\nRUNNING WITH {threads} THREADS\n{'='*30}\n")
        
        try:
            # Use Popen to stream output
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                encoding='utf-8',
                bufsize=1
            )
            
            # Read line by line to show progress and log
            with open(log_file, "a") as log:
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        print(line, end='') # Stream to console
                        full_output += line
                        # Detailed logging with timestamp
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        log.write(f"[{timestamp}] {line}")
                        log.flush()
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Extract metrics
            downloaded = 0
            skipped = 0
            errors = 0
            speed = 0.0
            
            m_down = re.search(r"Downloaded:\s+(\d+)", full_output)
            if m_down: downloaded = int(m_down.group(1))
            
            m_skip = re.search(r"Skipped \(Duplicates\):\s+(\d+)", full_output)
            if m_skip: skipped = int(m_skip.group(1))
            
            m_err = re.search(r"Final Errors:\s+(\d+)", full_output)
            if m_err: errors = int(m_err.group(1))
            
            m_speed = re.search(r"Average Speed:\s+([\d\.]+)", full_output)
            if m_speed: speed = float(m_speed.group(1))
            
            # Analyze for notes
            notes = ""
            if downloaded == 0 and skipped == 0:
                if "Authentication failed" in full_output:
                    notes = "Auth Failed"
                elif "Could not connect" in full_output:
                    notes = "Connection Failed"
                elif "Too many connections" in full_output or "socket" in full_output.lower():
                    notes = "Socket/Limit Error"
                else:
                    notes = "No Data/Crash"
            elif errors > 100:
                notes = "High Errors (Limit?)"
            
            # Check for specific connection errors in output even if some downloads succeeded
            if "Too many connections" in full_output:
                notes += " (Hit Conn Limit)"

            print(f"  -> Duration: {format_time(duration)}")
            print(f"  -> Speed: {speed:.2f} emails/h")
            print(f"  -> Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")
            if notes: print(f"  -> Note: {notes}")
            
            results.append({
                'threads': threads,
                'duration': duration,
                'speed': speed,
                'downloaded': downloaded,
                'skipped': skipped,
                'errors': errors,
                'notes': notes
            })
            
        except Exception as e:
            print(f"  -> Error running benchmark: {e}")
            with open(log_file, "a") as log:
                log.write(f"\n[ERROR] Exception in benchmark loop: {e}\n")
            results.append({
                'threads': threads,
                'duration': 0,
                'speed': 0,
                'downloaded': 0,
                'skipped': 0,
                'errors': -1,
                'notes': str(e)
            })

    # Generate Report
    report_file = "benchmark_results.md"
    with open(report_file, "w") as f:
        f.write(f"# Benchmark Results - {datetime.now().isoformat()}\n\n")
        f.write(f"**Email**: {email}\n")
        if days: f.write(f"**Days**: {days}\n")
        if start_date: f.write(f"**Start Date**: {start_date}\n")
        if end_date: f.write(f"**End Date**: {end_date}\n")
        f.write("\n")
        
        f.write("| Threads | Duration | Speed (emails/h) | Downloaded | Skipped | Errors | Notes |\n")
        f.write("|---------|----------|------------------|------------|---------|--------|-------|\n")
        
        for r in results:
            dur_fmt = format_time(r['duration'])
            f.write(f"| {r['threads']} | {dur_fmt} | {r['speed']:.2f} | {r['downloaded']} | {r['skipped']} | {r['errors']} | {r['notes']} |\n")
            
    print(f"\nBenchmark complete! Results saved to {report_file}")
    print(f"Detailed execution log saved to {log_file}")

if __name__ == '__main__':
    benchmark()
