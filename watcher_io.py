# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
watcher_io.py — Shared watchers.json read/write with file locking.
Single source of truth for watcher file I/O.
HGR
"""

import fcntl
import json
import os

import paths

WATCHERS_FILE = paths.WATCHERS_JSON
LOCK_FILE = WATCHERS_FILE + '.lock'


def load_watchers():
    if not os.path.exists(WATCHERS_FILE):
        return []
    with open(WATCHERS_FILE) as f:
        fcntl.flock(f, fcntl.LOCK_SH)  # shared lock for reads
        data = json.load(f)
        fcntl.flock(f, fcntl.LOCK_UN)
        return data


def save_watchers(watchers):
    os.makedirs(os.path.dirname(WATCHERS_FILE), exist_ok=True)
    lock_fd = open(LOCK_FILE, 'w')
    fcntl.flock(lock_fd, fcntl.LOCK_EX)  # exclusive lock for writes
    try:
        tmp = WATCHERS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(watchers, f, indent=2)
        os.replace(tmp, WATCHERS_FILE)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
