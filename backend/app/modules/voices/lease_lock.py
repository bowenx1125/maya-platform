"""Non-blocking one-file leases on Unix and Windows."""

from __future__ import annotations

import os
from importlib import import_module
from typing import BinaryIO

if os.name == "nt":
    msvcrt = import_module("msvcrt")
else:
    fcntl = import_module("fcntl")


def lock_exclusive(handle: BinaryIO) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(handle: BinaryIO) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
