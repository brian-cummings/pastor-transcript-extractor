from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


@dataclass(frozen=True, slots=True)
class FilesystemCapacity:
    available_bytes: int
    source: str
    filesystem_type: str | None = None
    portable_available_bytes: int | None = None


class _DarwinFsid(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int32 * 2)]


class _DarwinStatfs(ctypes.Structure):
    # Darwin's struct statfs, as declared in sys/mount.h. Keep this private: it
    # is used only behind the sys.platform guard below.
    _fields_ = [
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", _DarwinFsid),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * 16),
        ("f_mntonname", ctypes.c_char * 1024),
        ("f_mntfromname", ctypes.c_char * 1024),
        ("f_reserved", ctypes.c_uint32 * 8),
    ]


@dataclass(frozen=True, slots=True)
class _DarwinCapacity:
    available_bytes: int
    filesystem_type: str


def filesystem_capacity(path: Path) -> FilesystemCapacity:
    """Return usable destination capacity with a guarded macOS SMB correction.

    Python's statvfs-backed disk_usage can report a much smaller filesystem on
    some macOS SMB mounts. Darwin statfs is the native source used for mount
    statistics and supplies both the filesystem type and usable block count.
    Other platforms and non-SMB filesystems retain the portable implementation.
    """
    portable_error: OSError | None = None
    portable_available: int | None = None
    try:
        portable_available = shutil.disk_usage(path).free
    except OSError as error:
        portable_error = error

    if sys.platform == "darwin":
        try:
            native = _darwin_filesystem_capacity(path)
        except OSError:
            native = None
        if native is not None and native.filesystem_type == "smbfs":
            return FilesystemCapacity(
                available_bytes=native.available_bytes,
                source="darwin_statfs",
                filesystem_type=native.filesystem_type,
                portable_available_bytes=portable_available,
            )

    if portable_available is not None:
        return FilesystemCapacity(
            available_bytes=portable_available,
            source="shutil_disk_usage",
        )
    assert portable_error is not None
    raise portable_error


def _darwin_filesystem_capacity(path: Path) -> _DarwinCapacity:
    libc = ctypes.CDLL(None, use_errno=True)
    statfs = libc.statfs
    statfs.argtypes = [ctypes.c_char_p, ctypes.POINTER(_DarwinStatfs)]
    statfs.restype = ctypes.c_int
    result = _DarwinStatfs()
    if statfs(os.fsencode(path), ctypes.byref(result)) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(path))
    filesystem_type = bytes(result.f_fstypename).split(b"\0", 1)[0].decode(
        "ascii", errors="replace"
    )
    return _DarwinCapacity(
        available_bytes=result.f_bavail * result.f_bsize,
        filesystem_type=filesystem_type,
    )
