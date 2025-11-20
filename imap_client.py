import re
import imaplib
import socket
import ssl
from datetime import datetime
from typing import Optional, Tuple, List

class AutoIMAPClient:
    """
    A wrapper around imaplib to handle auto-discovery of IMAP servers
    and simplify connection/fetching.
    """
    
    # Set a global timeout for all socket operations to prevent hanging threads
    socket.setdefaulttimeout(10)
    
    # Common providers mapping for faster lookup
    COMMON_PROVIDERS = {
        'gmail.com': 'imap.gmail.com',
        'googlemail.com': 'imap.gmail.com',
        'outlook.com': 'outlook.office365.com',
        'hotmail.com': 'outlook.office365.com',
        'live.com': 'outlook.office365.com',
        'yahoo.com': 'imap.mail.yahoo.com',
        'icloud.com': 'imap.mail.me.com',
        'me.com': 'imap.mail.me.com',
        'mac.com': 'imap.mail.me.com',
        'uol.com.br': 'imap.uol.com.br',
        'bol.com.br': 'imap.bol.com.br',
        'terra.com.br': 'imap.terra.com.br',
    }

    def __init__(self, email_address: str, password: str):
        self.email_address = email_address
        self.password = password
        self.domain = email_address.split('@')[1].lower()
        self.connection: Optional[imaplib.IMAP4_SSL] = None
        self.server_address: Optional[str] = None

    def _guess_server(self) -> List[str]:
        """Generates a list of potential IMAP servers to try."""
        candidates = []
        
        # 1. Check common providers list
        if self.domain in self.COMMON_PROVIDERS:
            candidates.append(self.COMMON_PROVIDERS[self.domain])
        
        # 2. Standard prefixes
        candidates.append(f"imap.{self.domain}")
        candidates.append(f"mail.{self.domain}")
        
        return candidates

    def connect(self, server_hostname: Optional[str] = None, verbose: bool = True) -> bool:
        """
        Attempts to connect to the IMAP server.
        If server_hostname is provided, connects directly to it.
        Otherwise, uses auto-discovery.
        Returns True if successful, False otherwise.
        """
        if server_hostname:
            potential_servers = [server_hostname]
        else:
            potential_servers = self._guess_server()
        
        for server in potential_servers:
            try:
                if verbose:
                    print(f"Attempting to connect to {server}...")
                # Try SSL first (port 993)
                self.connection = imaplib.IMAP4_SSL(server, 993, timeout=10)
                self.connection.login(self.email_address, self.password)
                self.server_address = server
                if verbose:
                    print(f"Successfully connected to {server}!")
                return True
            except (imaplib.IMAP4.error, socket.gaierror, socket.timeout, ssl.SSLError) as e:
                if verbose:
                    print(f"Failed to connect to {server}: {e}")
                continue
        
        return False

    def list_folders(self) -> List[str]:
        """
        Lists all available folders on the server, excluding Spam/Junk.
        Allows Trash/Bin.
        """
        if not self.connection:
            return []
            
        try:
            typ, data = self.connection.list()
            if typ != 'OK':
                return []
            
            folders = []

            # Regex to capture folder name. 
            # Matches: ... "Delimiter" "Name"  OR  ... "Delimiter" Name
            # We focus on the last part.
            pattern = re.compile(r'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]+)"\s+(?P<name>.+)')
            
            for line in data:
                try:
                    decoded_line = line.decode()
                    match = pattern.search(decoded_line)
                    if match:
                        name = match.group('name')
                        # Remove surrounding quotes if present and unescape
                        if name.startswith('"') and name.endswith('"'):
                            name = name[1:-1]
                            name = name.replace('\\"', '"').replace('\\\\', '\\')
                        
                        # Filter Spam/Junk but allow Trash
                        lower_name = name.lower()
                        if ('spam' in lower_name or 'junk' in lower_name or 'bulk' in lower_name) and 'trash' not in lower_name:
                            continue
                            
                        folders.append(name)
                except:
                    continue
            
            return folders
        except:
            return []

    def select_folder(self, folder: str = 'INBOX', readonly: bool = True) -> bool:
        """Selects a folder (mailbox). Handles quoting."""
        if not self.connection:
            return False
        try:
            # IMAP requires quoted folder names if they contain spaces or special chars.
            target_folder = folder
            if ' ' in folder or '\\' in folder:
                if not folder.startswith('"'):
                    # Escape existing backslashes and quotes
                    escaped = folder.replace('\\', '\\\\').replace('"', '\\"')
                    target_folder = f'"{escaped}"'
            
            typ, _ = self.connection.select(target_folder, readonly=readonly)
            return typ == 'OK'
        except Exception as e:
            return False

    def fetch_email_ids(self, folder: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[bytes]:
        """
        Fetches email UIDs from a specific folder based on date filters.
        """
        if not self.connection:
            raise RuntimeError("Not connected to IMAP server.")

        if not self.select_folder(folder, readonly=True):
            print(f"Failed to select folder: {folder} (Skipping)")
            return []
        
        search_criteria = []
        
        if start_date:
            # IMAP date format: DD-Mon-YYYY
            fmt_date = start_date.strftime("%d-%b-%Y")
            search_criteria.append(f'(SINCE "{fmt_date}")')
        
        if end_date:
            fmt_date = end_date.strftime("%d-%b-%Y")
            search_criteria.append(f'(BEFORE "{fmt_date}")')
            
        if not search_criteria:
            search_criteria.append('ALL')
            
        criteria_str = ' '.join(search_criteria)
        
        try:
            # Use UID search for consistency across connections
            typ, data = self.connection.uid('search', None, criteria_str)
            if typ != 'OK':
                return []
            return data[0].split()
        except Exception as e:
            print(f"IMAP search error in {folder}: {e}")
            return []

    def fetch_message_id(self, email_uid: bytes) -> Optional[str]:
        """Fetches the Message-ID header for a specific email UID."""
        if not self.connection:
            return None
        try:
            # Fetch only the Message-ID header
            typ, data = self.connection.uid('fetch', email_uid, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
            if typ != 'OK':
                return None
            
            # Parse response to extract Message-ID
            for part in data:
                if isinstance(part, tuple):
                    header_content = part[1].decode(errors='ignore')
                    # Extract value after "Message-ID:"
        
                    match = re.search(r'Message-ID:\s*(<[^>]+>|[^(\r\n)]+)', header_content, re.IGNORECASE)
                    if match:
                        return match.group(1).strip()
            return None
        except Exception:
            return None

    def fetch_email_content(self, email_id: bytes) -> Optional[bytes]:
        """
        Fetches the raw content of a single email using UID.
        """
        if not self.connection:
            raise RuntimeError("Not connected.")
            
        try:
            # Use UID fetch
            typ, data = self.connection.uid('fetch', email_id, '(RFC822)')
            if typ != 'OK':
                return None
                
            # data[0] is a tuple (header, content) usually
            for response_part in data:
                if isinstance(response_part, tuple):
                    return response_part[1]
            return None
        except:
            return None

    def close(self):
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection.logout()
