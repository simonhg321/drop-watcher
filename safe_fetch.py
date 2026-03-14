# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
safe_fetch.py — SSRF-safe URL fetching for Drop Watcher.
Blocks requests to private/internal IPs, metadata endpoints, and non-HTTP schemes.
Used by watcher_signup.py (check-url) and per_user_alerter.py.
HGR
"""

import ipaddress
import socket
from urllib.parse import urlparse


# Private/reserved IP ranges that should never be fetched
BLOCKED_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8'),       # loopback
    ipaddress.ip_network('10.0.0.0/8'),         # private
    ipaddress.ip_network('172.16.0.0/12'),      # private
    ipaddress.ip_network('192.168.0.0/16'),     # private
    ipaddress.ip_network('169.254.0.0/16'),     # link-local / cloud metadata
    ipaddress.ip_network('0.0.0.0/8'),          # unspecified
    ipaddress.ip_network('100.64.0.0/10'),      # carrier-grade NAT
    ipaddress.ip_network('198.18.0.0/15'),      # benchmarking
    ipaddress.ip_network('::1/128'),            # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),           # IPv6 private
    ipaddress.ip_network('fe80::/10'),          # IPv6 link-local
]


def is_safe_url(url):
    """
    Validate that a URL is safe to fetch:
    - Must be http:// or https://
    - Hostname must resolve to a public IP (not private/internal)
    Returns (safe: bool, reason: str)
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL."

    # Scheme check
    if parsed.scheme not in ('http', 'https'):
        return False, "Only http:// and https:// URLs are supported."

    # Must have a hostname
    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname found in URL."

    # Block obvious metadata hostnames
    if hostname in ('metadata.google.internal', 'metadata', 'instance-data'):
        return False, "That URL is not allowed."

    # Resolve hostname to IP and check against blocklist
    try:
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "We can't resolve that hostname. Check the URL."

    for family, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for network in BLOCKED_NETWORKS:
            if ip in network:
                return False, "That URL points to an internal or reserved address."

    return True, "ok"
