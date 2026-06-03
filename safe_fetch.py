# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
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

    saw_valid_ip = False
    for family, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0].split('%')[0]   # strip IPv6 zone id (fe80::1%eth0)
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # Unparseable address from the resolver — fail closed, don't skip it.
            return False, "That URL points to an unsupported address."
        # Unwrap IPv4-mapped/compatible IPv6 (e.g. ::ffff:169.254.169.254) so it's
        # checked as the IPv4 it really reaches — otherwise it slips past the
        # IPv4-listed blocklist and hits loopback/cloud-metadata.
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        saw_valid_ip = True
        # Categorical safety net beyond the explicit list (covers reserved ranges,
        # multicast, etc. the manual list might miss).
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False, "That URL points to an internal or reserved address."
        for network in BLOCKED_NETWORKS:
            if ip in network:
                return False, "That URL points to an internal or reserved address."

    if not saw_valid_ip:
        return False, "We can't resolve that hostname. Check the URL."

    return True, "ok"


def safe_get(url, headers=None, timeout=10, max_redirects=4):
    """SSRF-safe HTTP GET.

    Validates the URL and EVERY redirect hop against is_safe_url (resolving
    relative Location headers), following at most max_redirects. Without this,
    a public host that 302s to http://169.254.169.254/ would be followed
    server-side and reach cloud metadata / loopback.

    Returns the final requests.Response. Raises ValueError(reason) if any hop is
    unsafe or the redirect chain is too long; lets requests' own exceptions
    (Timeout, ConnectionError, …) propagate so callers can message them.
    """
    import requests
    from urllib.parse import urljoin

    current = url
    for _ in range(max_redirects + 1):
        safe, reason = is_safe_url(current)
        if not safe:
            raise ValueError(reason)
        r = requests.get(current, headers=headers, timeout=timeout, allow_redirects=False)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get('Location', '')
            if not loc:
                return r
            current = urljoin(current, loc)   # resolve relative redirects to absolute
            continue
        return r
    raise ValueError("Too many redirects.")
