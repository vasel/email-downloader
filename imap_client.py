import re
import imaplib
import socket
import ssl
import struct
from datetime import datetime
from typing import Optional, Tuple, List
import urllib.request
import xml.etree.ElementTree as ET

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

    # MX pattern → IMAP server mapping for hosted email providers
    # Each entry: (substring in MX hostname, IMAP server to use)
    MX_PROVIDER_MAP = [
        # Google Workspace / G Suite
        ('google.com',       'imap.gmail.com'),
        ('googlemail.com',   'imap.gmail.com'),
        # Microsoft 365 / Exchange Online
        ('outlook.com',      'outlook.office365.com'),
        ('protection.outlook.com', 'outlook.office365.com'),
        ('microsoft.com',    'outlook.office365.com'),
        # Yahoo
        ('yahoodns.net',     'imap.mail.yahoo.com'),
        ('yahoo.com',        'imap.mail.yahoo.com'),
        # Zoho
        ('zoho.com',         'imap.zoho.com'),
        ('zoho.eu',          'imap.zoho.eu'),
        ('zoho.in',          'imap.zoho.in'),
        # ProtonMail (Bridge required — not directly useful, but good to detect)
        ('protonmail.ch',    'imap.protonmail.ch'),
        # Locaweb (BR)
        ('locaweb.com.br',   'imap.email-ssl.com.br'),
        # GoDaddy (Secureserver / Asia)
        ('secureserver.net', 'imap.secureserver.net'),
        # Titan Email (used by many custom domains)
        ('titan.email',      'imap.titan.email'),
        # Rackspace
        ('emailsrvr.com',    'secure.emailsrvr.com'),
        # FastMail
        ('messagingengine.com', 'imap.fastmail.com'),
        # UOL/BOL (BR)
        ('uol.com.br',       'imap.uol.com.br'),
    ]

    def __init__(self, email_address: str, password: str):
        self.email_address = email_address
        self.password = password
        self.domain = email_address.split('@')[1].lower()
        self.connection: Optional[imaplib.IMAP4_SSL] = None
        self.server_address: Optional[str] = None
        self.detected_provider: Optional[str] = None  # Friendly name of detected provider
        self.connection_attempts: List[Tuple[str, str]] = [] # List of (server, error)

    def _resolve_mx_records(self) -> List[str]:
        """
        Resolves MX records for the domain using raw DNS over UDP (no external dependencies).
        Returns a list of MX hostnames sorted by priority (lowest first).
        """
        try:
            response = self._resolve_dns_query(self.domain, 15)  # MX = 15
            if not response:
                return []
            return self._parse_dns_mx_response(response)
        except Exception:
            return []

    def _get_system_dns(self) -> List[str]:
        """Gets system DNS servers (Windows-compatible)."""
        import subprocess
        dns_servers = []
        try:
            # Use ipconfig /all on Windows to find DNS servers
            import platform
            if platform.system() == 'Windows':
                result = subprocess.run(
                    ['ipconfig', '/all'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'DNS' in line and ':' in line:
                        parts = line.split(':')
                        if len(parts) >= 2:
                            ip = parts[-1].strip()
                            if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                                dns_servers.append(ip)
            else:
                # Linux/Mac: read /etc/resolv.conf
                with open('/etc/resolv.conf', 'r') as f:
                    for line in f:
                        if line.strip().startswith('nameserver'):
                            ip = line.strip().split()[1]
                            dns_servers.append(ip)
        except Exception:
            pass
        return dns_servers

    def _parse_dns_mx_response(self, response: bytes) -> List[str]:
        """Parses a raw DNS response and extracts MX records."""
        mx_records = []
        try:
            # Skip header (12 bytes)
            # Parse QDCOUNT, ANCOUNT from header
            qdcount = struct.unpack('>H', response[4:6])[0]
            ancount = struct.unpack('>H', response[6:8])[0]
            
            offset = 12  # Skip header
            
            # Skip question section
            for _ in range(qdcount):
                while response[offset] != 0:
                    label_len = response[offset]
                    if label_len >= 192:  # Pointer
                        offset += 2
                        break
                    offset += label_len + 1
                else:
                    offset += 1  # Skip null byte
                offset += 4  # Skip QTYPE and QCLASS
            
            # Parse answer section
            for _ in range(ancount):
                # Parse name (may be pointer)
                if response[offset] >= 192:  # Pointer
                    offset += 2
                else:
                    while response[offset] != 0:
                        offset += response[offset] + 1
                    offset += 1
                
                rtype = struct.unpack('>H', response[offset:offset+2])[0]
                rdlength = struct.unpack('>H', response[offset+8:offset+10])[0]
                offset += 10  # Skip TYPE, CLASS, TTL, RDLENGTH
                
                if rtype == 15:  # MX record
                    priority = struct.unpack('>H', response[offset:offset+2])[0]
                    # Parse exchange domain name
                    exchange = self._read_dns_name(response, offset + 2)
                    if exchange:
                        mx_records.append((priority, exchange.lower().rstrip('.')))
                
                offset += rdlength
            
            # Sort by priority
            mx_records.sort(key=lambda x: x[0])
            return [mx[1] for mx in mx_records]
            
        except Exception:
            return []

    def _read_dns_name(self, response: bytes, offset: int) -> str:
        """Reads a DNS domain name from a response, handling compression pointers."""
        labels = []
        visited = set()  # Prevent infinite loops
        
        while offset < len(response):
            if offset in visited:
                break
            visited.add(offset)
            
            length = response[offset]
            
            if length == 0:
                break
            elif length >= 192:  # Compression pointer
                pointer = struct.unpack('>H', response[offset:offset+2])[0] & 0x3FFF
                rest = self._read_dns_name(response, pointer)
                if rest:
                    labels.append(rest)
                break
            else:
                offset += 1
                label = response[offset:offset+length].decode('ascii', errors='ignore')
                labels.append(label)
                offset += length
        
        return '.'.join(labels)

    def _detect_provider_from_mx(self) -> Optional[str]:
        """
        Resolves MX records for the domain and maps them to a known IMAP server.
        Returns the IMAP hostname if a known provider is detected, otherwise None.
        """
        try:
            mx_hosts = self._resolve_mx_records()
            if not mx_hosts:
                return None
            
            for mx_host in mx_hosts:
                for pattern, imap_server in self.MX_PROVIDER_MAP:
                    if mx_host.endswith(pattern) or pattern in mx_host:
                        # Set a friendly name for user feedback
                        if 'google' in pattern or 'gmail' in pattern:
                            self.detected_provider = 'Google Workspace (G Suite)'
                        elif 'outlook' in pattern or 'microsoft' in pattern:
                            self.detected_provider = 'Microsoft 365'
                        elif 'yahoo' in pattern:
                            self.detected_provider = 'Yahoo Mail'
                        elif 'zoho' in pattern:
                            self.detected_provider = 'Zoho Mail'
                        elif 'locaweb' in pattern:
                            self.detected_provider = 'Locaweb'
                        elif 'titan' in pattern:
                            self.detected_provider = 'Titan Email'
                        elif 'fastmail' in pattern or 'messagingengine' in pattern:
                            self.detected_provider = 'FastMail'
                        else:
                            self.detected_provider = imap_server
                        return imap_server
        except Exception:
            pass
        return None

    def _resolve_dns_query(self, domain: str, qtype: int) -> bytes:
        """
        Sends a raw DNS query and returns the response bytes.
        qtype: 15=MX, 16=TXT, 33=SRV
        """
        import random
        txn_id = random.randint(0, 65535)
        header = struct.pack('>HHHHHH', txn_id, 0x0100, 1, 0, 0, 0)
        
        question = b''
        for part in domain.split('.'):
            question += struct.pack('B', len(part)) + part.encode('ascii')
        question += b'\x00'
        question += struct.pack('>HH', qtype, 1)  # QTYPE, QCLASS=IN
        
        query = header + question
        
        dns_servers = self._get_system_dns()
        if not dns_servers:
            dns_servers = ['8.8.8.8', '1.1.1.1']
        
        for dns_server in dns_servers:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(5)
                sock.sendto(query, (dns_server, 53))
                response, _ = sock.recvfrom(4096)
                sock.close()
                if response:
                    return response
            except Exception:
                continue
        return b''

    def _resolve_srv_record(self, service: str) -> Optional[str]:
        """
        Resolves a DNS SRV record (e.g. _autodiscover._tcp.domain).
        Returns the target hostname if found, otherwise None.
        """
        try:
            srv_domain = f"{service}.{self.domain}"
            response = self._resolve_dns_query(srv_domain, 33)  # SRV = 33
            if not response:
                return None
            
            # Parse response
            qdcount = struct.unpack('>H', response[4:6])[0]
            ancount = struct.unpack('>H', response[6:8])[0]
            
            offset = 12
            # Skip question section
            for _ in range(qdcount):
                while response[offset] != 0:
                    label_len = response[offset]
                    if label_len >= 192:
                        offset += 2
                        break
                    offset += label_len + 1
                else:
                    offset += 1
                offset += 4
            
            # Parse answers
            best_priority = 65535
            best_target = None
            
            for _ in range(ancount):
                # Skip name
                if response[offset] >= 192:
                    offset += 2
                else:
                    while response[offset] != 0:
                        offset += response[offset] + 1
                    offset += 1
                
                rtype = struct.unpack('>H', response[offset:offset+2])[0]
                rdlength = struct.unpack('>H', response[offset+8:offset+10])[0]
                offset += 10
                
                if rtype == 33:  # SRV
                    priority = struct.unpack('>H', response[offset:offset+2])[0]
                    # weight at offset+2, port at offset+4
                    target = self._read_dns_name(response, offset + 6)
                    if target and priority < best_priority:
                        best_priority = priority
                        best_target = target.lower().rstrip('.')
                
                offset += rdlength
            
            return best_target
        except Exception:
            return None

    def _resolve_txt_records(self) -> List[str]:
        """
        Resolves DNS TXT records for the domain.
        Returns a list of TXT record strings.
        """
        txt_records = []
        try:
            response = self._resolve_dns_query(self.domain, 16)  # TXT = 16
            if not response:
                return []
            
            qdcount = struct.unpack('>H', response[4:6])[0]
            ancount = struct.unpack('>H', response[6:8])[0]
            
            offset = 12
            # Skip question section
            for _ in range(qdcount):
                while response[offset] != 0:
                    label_len = response[offset]
                    if label_len >= 192:
                        offset += 2
                        break
                    offset += label_len + 1
                else:
                    offset += 1
                offset += 4
            
            # Parse answers
            for _ in range(ancount):
                # Skip name
                if response[offset] >= 192:
                    offset += 2
                else:
                    while response[offset] != 0:
                        offset += response[offset] + 1
                    offset += 1
                
                rtype = struct.unpack('>H', response[offset:offset+2])[0]
                rdlength = struct.unpack('>H', response[offset+8:offset+10])[0]
                rdata_start = offset + 10
                offset += 10
                
                if rtype == 16:  # TXT
                    # TXT RDATA: one or more <length><string> chunks
                    txt_parts = []
                    pos = rdata_start
                    end = rdata_start + rdlength
                    while pos < end:
                        str_len = response[pos]
                        pos += 1
                        txt_parts.append(response[pos:pos+str_len].decode('utf-8', errors='ignore'))
                        pos += str_len
                    txt_records.append(''.join(txt_parts))
                
                offset = rdata_start + rdlength
                
        except Exception:
            pass
        return txt_records

    def _detect_provider_from_srv(self) -> Optional[str]:
        """
        Checks DNS SRV records for autodiscover service.
        Office 365 domains typically have:
          _autodiscover._tcp.domain → autodiscover.outlook.com
        Returns the IMAP hostname if a known provider is detected.
        """
        try:
            target = self._resolve_srv_record('_autodiscover._tcp')
            if target:
                if 'outlook.com' in target or 'microsoft.com' in target:
                    self.detected_provider = 'Microsoft 365'
                    return 'outlook.office365.com'
                elif 'google.com' in target or 'gmail.com' in target:
                    self.detected_provider = 'Google Workspace (G Suite)'
                    return 'imap.gmail.com'
        except Exception:
            pass
        return None

    def _detect_provider_from_spf(self) -> Optional[str]:
        """
        Analyzes SPF (TXT) records to detect the underlying email provider.
        SPF records reveal the actual sending infrastructure even when MX
        points to a security gateway.
        
        Examples:
          "v=spf1 include:spf.protection.outlook.com ~all"  → Office 365
          "v=spf1 include:_spf.google.com ~all"             → Google Workspace
        """
        # Provider patterns in SPF records: (pattern, imap_server, provider_name)
        SPF_PATTERNS = [
            ('spf.protection.outlook.com', 'outlook.office365.com', 'Microsoft 365'),
            ('protection.outlook.com',     'outlook.office365.com', 'Microsoft 365'),
            ('outlook.com',                'outlook.office365.com', 'Microsoft 365'),
            ('_spf.google.com',            'imap.gmail.com',        'Google Workspace (G Suite)'),
            ('google.com',                 'imap.gmail.com',        'Google Workspace (G Suite)'),
            ('googlemail.com',             'imap.gmail.com',        'Google Workspace (G Suite)'),
            ('zoho.com',                   'imap.zoho.com',         'Zoho Mail'),
            ('messagingengine.com',        'imap.fastmail.com',     'FastMail'),
            ('yahoodns.net',               'imap.mail.yahoo.com',   'Yahoo Mail'),
        ]
        
        try:
            txt_records = self._resolve_txt_records()
            for record in txt_records:
                record_lower = record.lower()
                if not record_lower.startswith('v=spf1'):
                    continue
                # Found SPF record — check for known providers
                for pattern, imap_server, provider_name in SPF_PATTERNS:
                    if pattern in record_lower:
                        self.detected_provider = provider_name
                        return imap_server
        except Exception:
            pass
        return None

    # Known email security gateways that sit in front of the real mail provider
    EMAIL_SECURITY_GATEWAYS = [
        'trendmicro.com',
        'tmes.trendmicro.com',
        'proofpoint.com',
        'pphosted.com',
        'mimecast.com',
        'barracuda.com',
        'barracudanetworks.com',
        'forcepoint.com',
        'fireeye.com',
        'cisco.com',
        'iphmx.com',          # Cisco IronPort
        'sophos.com',
        'messagelabs.com',     # Symantec/Broadcom
        'symantec.com',
        'reflexion.net',
        'hornetsecurity.com',
        'spamexperts.com',
    ]

    def _is_security_gateway(self, mx_hosts: List[str]) -> bool:
        """Checks if MX records point to a known email security gateway."""
        for mx in mx_hosts:
            for gw in self.EMAIL_SECURITY_GATEWAYS:
                if gw in mx:
                    return True
        return False

    def _lookup_mozilla_autoconfig(self) -> Optional[str]:
        """
        Queries the domain's own Mozilla autoconfig endpoint.
        Many mail providers host autoconfig XML at:
          https://autoconfig.{domain}/mail/config-v1.1.xml
          or
          https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml
        Returns the IMAP hostname if found, otherwise None.
        """
        urls = [
            f"https://autoconfig.{self.domain}/mail/config-v1.1.xml",
            f"http://autoconfig.{self.domain}/mail/config-v1.1.xml",
            f"https://{self.domain}/.well-known/autoconfig/mail/config-v1.1.xml",
            f"http://{self.domain}/.well-known/autoconfig/mail/config-v1.1.xml",
        ]
        
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'EmailDownloader/1.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        tree = ET.parse(response)
                        root = tree.getroot()
                        # Handle namespaced XML
                        ns = ''
                        if root.tag.startswith('{'):
                            ns = root.tag.split('}')[0] + '}'
                        
                        for server in root.findall(f".//{ns}incomingServer"):
                            if server.get('type') == 'imap':
                                hostname = server.find(f'{ns}hostname')
                                if hostname is not None and hostname.text:
                                    return hostname.text.strip()
            except Exception:
                continue
        return None

    def _lookup_thunderbird_config(self) -> Optional[str]:
        """
        Queries Thunderbird's autoconfig service for the domain.
        Returns the hostname if found, otherwise None.
        """
        try:
            url = f"https://autoconfig.thunderbird.net/v1.1/{self.domain}"
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    tree = ET.parse(response)
                    root = tree.getroot()
                    # Look for <incomingServer type="imap">
                    for server in root.findall(".//incomingServer"):
                        if server.get('type') == 'imap':
                            hostname = server.find('hostname')
                            if hostname is not None:
                                return hostname.text
        except Exception:
            pass
        return None

    def _guess_server(self) -> List[str]:
        """
        Generates a prioritized list of potential IMAP servers to try.
        
        Discovery order:
        1. Hardcoded common providers (instant)
        2. DNS MX record analysis (detects Google Workspace, Microsoft 365, etc.)
        3. DNS SRV autodiscover (detects Office 365 behind security gateways)
        4. DNS SPF/TXT analysis (detects provider from SPF includes)
        5. Mozilla autoconfig on the domain itself
        6. Thunderbird ISPDB autoconfig
        7. Standard prefix guesses (imap.domain, mail.domain)
        """
        candidates = []
        
        # 1. Check common providers list (instant, no network)
        if self.domain in self.COMMON_PROVIDERS:
            candidates.append(self.COMMON_PROVIDERS[self.domain])
        
        # 2. DNS MX record analysis — detect hosted providers
        mx_imap = self._detect_provider_from_mx()
        if mx_imap and mx_imap not in candidates:
            candidates.insert(0 if not candidates else len(candidates), mx_imap)
            if candidates and candidates[0] != mx_imap:
                candidates.remove(mx_imap)
                candidates.insert(0, mx_imap)
        
        # 3. If MX didn't match a provider (possibly a security gateway),
        #    try SRV and SPF to discover the real provider
        if not mx_imap:
            # 3a. DNS SRV autodiscover
            srv_imap = self._detect_provider_from_srv()
            if srv_imap and srv_imap not in candidates:
                candidates.insert(0, srv_imap)
            
            # 3b. DNS SPF/TXT analysis
            if not srv_imap:
                spf_imap = self._detect_provider_from_spf()
                if spf_imap and spf_imap not in candidates:
                    candidates.insert(0, spf_imap)
        
        # 4. Mozilla autoconfig on the domain itself
        domain_autoconfig = self._lookup_mozilla_autoconfig()
        if domain_autoconfig and domain_autoconfig not in candidates:
            candidates.append(domain_autoconfig)
        
        # 5. Thunderbird ISPDB Autoconfig
        tb_config = self._lookup_thunderbird_config()
        if tb_config and tb_config not in candidates:
            candidates.append(tb_config)
        
        # 6. Standard prefix guesses (fallback)
        standard_guesses = [f"imap.{self.domain}", f"mail.{self.domain}"]
        for guess in standard_guesses:
            if guess not in candidates:
                candidates.append(guess)
        
        return candidates

    def detect_server(self, verbose: bool = True) -> dict:
        """
        Runs the full server discovery pipeline WITHOUT connecting or authenticating.
        Returns a dict with discovery results:
        {
            'domain': str,
            'detected_provider': str or None,
            'mx_records': list[str],
            'candidates': list[str],
            'sources': dict[str, str],  # candidate -> how it was discovered
            'security_gateway': bool,
        }
        """
        results = {
            'domain': self.domain,
            'detected_provider': None,
            'mx_records': [],
            'candidates': [],
            'sources': {},
            'security_gateway': False,
        }

        # 1. Common providers
        if self.domain in self.COMMON_PROVIDERS:
            server = self.COMMON_PROVIDERS[self.domain]
            results['candidates'].append(server)
            results['sources'][server] = 'Common provider (hardcoded)'
            if verbose:
                print(f"  [Common]       {server}")

        # 2. MX records
        if verbose:
            print(f"  Resolving MX records for {self.domain}...")
        mx_hosts = self._resolve_mx_records()
        results['mx_records'] = mx_hosts
        if mx_hosts and verbose:
            for mx in mx_hosts:
                print(f"  [MX]           {mx}")

        mx_imap = self._detect_provider_from_mx()
        if mx_imap:
            results['detected_provider'] = self.detected_provider
            if mx_imap not in results['candidates']:
                results['candidates'].append(mx_imap)
                results['sources'][mx_imap] = f'MX records → {self.detected_provider or "matched pattern"}'
            if verbose:
                print(f"  [MX → IMAP]    {mx_imap}  ({self.detected_provider})")

        # 3. Check if MX points to a security gateway
        is_gateway = self._is_security_gateway(mx_hosts)
        results['security_gateway'] = is_gateway
        if is_gateway and verbose:
            print(f"  [MX]           ⚠ Email security gateway detected — probing deeper...")

        # 4. SRV autodiscover (always run if MX didn't find provider)
        if not mx_imap:
            if verbose:
                print(f"  Checking SRV _autodiscover._tcp.{self.domain}...")
            srv_imap = self._detect_provider_from_srv()
            if srv_imap:
                if not results['detected_provider']:
                    results['detected_provider'] = self.detected_provider
                if srv_imap not in results['candidates']:
                    results['candidates'].insert(0, srv_imap)
                    results['sources'][srv_imap] = f'SRV _autodiscover._tcp → {self.detected_provider}'
                if verbose:
                    print(f"  [SRV → IMAP]   {srv_imap}  ({self.detected_provider})")

        # 5. SPF/TXT analysis (if still no provider detected)
        if not results['detected_provider']:
            if verbose:
                print(f"  Checking SPF/TXT records for {self.domain}...")
            spf_imap = self._detect_provider_from_spf()
            if spf_imap:
                results['detected_provider'] = self.detected_provider
                if spf_imap not in results['candidates']:
                    results['candidates'].insert(0, spf_imap)
                    results['sources'][spf_imap] = f'SPF/TXT records → {self.detected_provider}'
                if verbose:
                    print(f"  [SPF → IMAP]   {spf_imap}  ({self.detected_provider})")

        # 6. Mozilla autoconfig
        if verbose:
            print(f"  Checking Mozilla autoconfig for {self.domain}...")
        domain_autoconfig = self._lookup_mozilla_autoconfig()
        if domain_autoconfig:
            if domain_autoconfig not in results['candidates']:
                results['candidates'].append(domain_autoconfig)
            results['sources'][domain_autoconfig] = results['sources'].get(domain_autoconfig, 'Mozilla autoconfig (domain)')
            if verbose:
                print(f"  [Autoconfig]   {domain_autoconfig}")

        # 7. Thunderbird ISPDB
        if verbose:
            print(f"  Checking Thunderbird ISPDB...")
        tb_config = self._lookup_thunderbird_config()
        if tb_config:
            if tb_config not in results['candidates']:
                results['candidates'].append(tb_config)
            results['sources'][tb_config] = results['sources'].get(tb_config, 'Thunderbird ISPDB')
            if verbose:
                print(f"  [Thunderbird]  {tb_config}")

        # 8. Standard guesses
        for guess in [f"imap.{self.domain}", f"mail.{self.domain}"]:
            if guess not in results['candidates']:
                results['candidates'].append(guess)
                results['sources'][guess] = 'Standard prefix guess'

        return results

    def connect(self, server_hostname: Optional[str] = None, port: int = 993, verbose: bool = True, use_ssl: bool = True) -> bool:
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
        
        self.connection_attempts = [] # Reset attempts on new connect call
        
        for server in potential_servers:
            try:
                if verbose:
                    print(f"Attempting to connect to {server}:{port} ({'SSL' if use_ssl else 'No-SSL'})...")
                
                if use_ssl:
                    self.connection = imaplib.IMAP4_SSL(server, port, timeout=10)
                else:
                    self.connection = imaplib.IMAP4(server, port, timeout=10)
                    
                self.connection.login(self.email_address, self.password)
                self.server_address = server
                if verbose:
                    print(f"Successfully connected to {server}!")
                return True
            except (imaplib.IMAP4.error, socket.gaierror, socket.timeout, ssl.SSLError) as e:
                error_msg = str(e)
                self.connection_attempts.append((server, error_msg))
                if verbose:
                    print(f"Failed to connect to {server}:{port}: {e}")
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
                        
                        # Exclude [Gmail]/Todos os e-mails and All Mail to avoid duplication
                        if 'todos os e-mails' in lower_name or 'all mail' in lower_name:
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
