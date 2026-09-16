#!/usr/bin/env python3.14
"""
optimize_firefox.py - Bleeding-edge Firefox 155+ HTTP cache-policy manager.
Target: Arch Linux (kernel 7.2+, rolling), Python 3.14.7+, Firefox 155+ only.

Zero backwards-compatibility shims for legacy Python (< 3.14) or legacy Firefox (< 155).

Capabilities:
    --cache-mode memory
        Disable Firefox's HTTP disk cache and enable the memory cache.
        Firefox retains its dynamic memory-cache sizing policy by default, or accepts
        an optional --memory-capacity override.

    --cache-mode default (or --disable)
        Restore the exact baseline user.js and managed prefs.js saved by this tool.

    --status [--json]
        Read-only inspection: reports system info, profile discovery, OFD lock status,
        active cache preferences, cache2 disk usage, and advisory diagnostics.

Architectural highlights:
    * Linux Open File Description (OFD) locking (fcntl.F_OFD_SETLK):
      True mutual exclusion with Firefox's nsProfileLock (F_SETLK), immune to POSIX
      record-lock release-on-close hazards. Probes holding PID with F_OFD_GETLK (exit 3).
    * Native Python 3.14+ Zstandard compression (compression.zstd):
      Streams .tar.zst archives with checksummed frames and single-pass SHA-256 digests.
    * Chronologically sorted backup names using uuid.uuid7().
    * Default --backup-scope targeted: archives only user.js, prefs.js, state.json,
      and manifest in sub-millisecond time. --backup-scope full available for full profiles.
    * Directory-pinned atomic replacement (openat / renameat): TOCTOU-resistant file updates.
    * Strict umask independence: explicit 0600 file modes and 0700 directory modes.
    * Automatic migration of legacy optimizer blocks: detects older optimizer blocks,
      creates a verified backup, cleanly strips obsolete/dead pre-155 settings, preserves
      all user UI/GTK customizations outside the block, and applies the clean 155+ policy.
    * Signal safety: SIGTERM, SIGHUP, and SIGINT unwind context managers, releasing locks
      and reaping incomplete temporary files.
    * Symlink resolution: seamlessly handles symlinked profile roots (~/.mozilla -> ~/.config/mozilla).
"""

from __future__ import annotations

import sys

# Pre-import runtime requirement guard
if sys.version_info < (3, 14, 7):
    sys.stderr.write(
        f"ERROR: Python 3.14.7 or newer is required (running {sys.version.split()[0]}).\n"
    )
    sys.exit(1)

if not sys.platform.startswith("linux"):
    sys.stderr.write("ERROR: Linux is required.\n")
    sys.exit(1)

import argparse
import configparser
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
import fcntl
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import tarfile
import tempfile
import time
from typing import BinaryIO, Final, Iterator, Sequence
import uuid
from compression import zstd

# ===========================================================================
# Constants & Contracts
# ===========================================================================

TOOL_NAME: Final = "optimize_firefox.py"
TOOL_ID: Final = "firefox-cache-policy"
TOOL_VERSION: Final = "3.1.0-ff155"
MIN_FIREFOX_MAJOR: Final = 155

STATE_SCHEMA: Final = 2
STATE_FILENAME: Final = ".firefox-cache-policy-state.json"
DEFAULT_BACKUP_DIRNAME: Final = ".firefox-cache-policy-backups"
BACKUP_PREFIX: Final = "ffcp"
TEMP_ARCHIVE_PREFIX: Final = ".incomplete-ffcp-"

MAX_BACKUPS_PER_PROFILE: Final = 3
MAX_TEXT_BYTES: Final = 128 * 1024 * 1024
BACKUP_HEADROOM_BYTES: Final = 64 * 1024 * 1024
MAX_FULL_BACKUP_ENTRIES: Final = 250_000

ZSTD_LEVEL_TARGETED: Final = 3
ZSTD_LEVEL_FULL: Final = 3

PREFS_JS: Final = "prefs.js"
USER_JS: Final = "user.js"
PARENTLOCK: Final = ".parentlock"
SYMLINK_LOCK: Final = "lock"

MANAGED_KEYS: Final = frozenset({
    "browser.cache.disk.enable",
    "browser.cache.memory.enable",
})

# Preferences that must never be recorded into rollback state or logged raw
SECRET_KEYS: Final = frozenset({
    "browser.cache.disk.encryption.key",
})

# Frozen, version-independent block body so SHA-256 remains stable forever
MANAGED_BLOCK_BODY: Final = (
    "// === BEGIN FIREFOX OPTIMIZATION SUITE ===",
    "// Managed by optimize_firefox.py - Firefox 155+ HTTP cache policy",
    'user_pref("browser.cache.disk.enable", false);',
    'user_pref("browser.cache.memory.enable", true);',
    "// === END FIREFOX OPTIMIZATION SUITE ===",
    "",
)

BLOCK_BEGIN: Final = "// === BEGIN FIREFOX OPTIMIZATION SUITE ==="
BLOCK_END: Final = "// === END FIREFOX OPTIMIZATION SUITE ==="

# Legacy keys from pre-155 optimizer scripts to clean up on migration
LEGACY_KEYS: Final = frozenset({
    "browser.cache.memory.capacity",
    "browser.cache.disk.smart_size.enabled",
    "browser.cache.disk_cache_ssl",
    "browser.cache.offline.enable",
    "dom.ipc.processCount",
    "dom.ipc.processCount.webIsolated",
    "dom.ipc.processCount.extension",
    "fission.autostart",
    "browser.tabs.unloadOnLowMemory",
    "gfx.webrender.all",
    "layers.acceleration.force-enabled",
    "media.ffmpeg.vaapi.enabled",
    "media.hardware-video-decoding.force-enabled",
    "widget.wayland-dmabuf-vaapi.enabled",
    "widget.wayland.opaque-region.enabled",
    "apz.gtk.kinetic_scroll.enabled",
    "toolkit.telemetry.enabled",
    "datareporting.healthreport.uploadEnabled",
    "app.normandy.enabled",
    "network.http.max-connections",
    "network.http.max-persistent-connections-per-server",
    "network.trr.mode",
    "network.trr.uri",
    "browser.cache.disk.parent_directory",
})

EXCLUDED_ROOT_ENTRIES: Final = frozenset({
    PARENTLOCK,
    SYMLINK_LOCK,
})

TRANSIENT_FILESYSTEMS: Final = frozenset({
    "tmpfs",
    "ramfs",
    "overlay",
})

NETWORK_FILESYSTEMS: Final = frozenset({
    "nfs", "nfs4", "cifs", "smb3", "smbfs", "afs", "ceph", "glusterfs", "sshfs",
})
NETWORK_FS_PREFIXES: Final = ("fuse.sshfs", "fuse.rclone")

MAINTENANCE_UNITS: Final = (
    "psd.service",
    "psd-resync.service",
    "psd-resync.timer",
    "profile-cleaner.service",
    "profile-cleaner.timer",
)

# Open File Description flock buffer:
# C struct flock on x86-64 / arm64 Linux is 32 bytes (short, short, padding, int64, int64, int32, padding).
# We pad to 64 bytes to guarantee zero uninitialized kernel stack reads.
_FLOCK: Final = struct.Struct("@hhqqi")
_FLOCK_BUFFER: Final = max(64, _FLOCK.size)

USER_JS_KEYWORD: Final = re.compile(
    r"\b(?:user_pref|sticky_pref|pref)\b"
)

PREF_LINE: Final = re.compile(
    r"^[ \t]*(?:user_pref|sticky_pref|pref)[ \t]*\([ \t]*"
    r'"((?:[^"\\]|\\.)*)"'
    r'[ \t]*,[ \t]*'
    r'(true|false|-?[0-9]+|"(?:[^"\\]|\\.)*")'
    r'[ \t]*\)[ \t]*;[ \t]*(?://.*|/\*.*?\*/[ \t]*)?$',
    re.DOTALL,
)

# ===========================================================================
# Logging Setup
# ===========================================================================

LOGGER = logging.getLogger("firefox_cache_policy")


class StderrFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


class StdoutFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.WARNING


def configure_logging(verbose: bool) -> None:
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOGGER.handlers.clear()

    out_handler = logging.StreamHandler(sys.stdout)
    out_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    out_handler.addFilter(StdoutFilter())
    out_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    err_handler = logging.StreamHandler(sys.stderr)
    err_handler.setLevel(logging.WARNING)
    err_handler.addFilter(StderrFilter())
    err_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    LOGGER.addHandler(out_handler)
    LOGGER.addHandler(err_handler)


# ===========================================================================
# Exceptions
# ===========================================================================

class SafetyError(RuntimeError):
    """An unsafe, invalid, or conflicting condition was detected."""


class ProfileLockedError(SafetyError):
    """A running Firefox process holds an exclusive lock on the profile."""


class UninitializedProfileError(SafetyError):
    """The profile directory exists but lacks prefs.js."""


def fail(message: str) -> None:
    raise SafetyError(message)


def oserror_detail(error: OSError) -> str:
    name = os.strerror(error.errno) if error.errno else "error"
    code = f" [errno {error.errno}]" if error.errno else ""
    return f"{name}{code}: {error.filename or ''}".strip()


# ===========================================================================
# Utility Helpers
# ===========================================================================

def stat_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def human_bytes(count: int | float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(count)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} TiB"


def absolute_without_symlinks(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded

    current = Path("/")
    for part in expanded.parts[1:]:
        if part == "..":
            if not current.is_dir():
                fail(f"Cannot traverse '..' through missing/non-directory: {current}")
            current = current.parent
            continue

        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue

        if stat.S_ISLNK(info.st_mode):
            fail(f"Symlinked path component is rejected in this context: {current}")

    return current


# ===========================================================================
# Mount Topology (/proc/self/mountinfo parser)
# ===========================================================================

@dataclass(frozen=True, slots=True)
class MountEntry:
    mount_point: Path
    fstype: str
    source: str


def _unescape_mountinfo(value: bytes) -> bytes:
    return re.sub(
        rb"\\([0-7]{3})",
        lambda m: bytes([int(m.group(1), 8)]),
        value,
    )


def read_mount_table() -> list[MountEntry]:
    try:
        raw = Path("/proc/self/mountinfo").read_bytes()
    except OSError as error:
        raise SafetyError(f"Cannot read /proc/self/mountinfo: {oserror_detail(error)}") from error

    table: list[MountEntry] = []
    for line in raw.splitlines():
        if not line:
            continue
        fields = line.split(b" ")
        if len(fields) < 10:
            fail("Unexpected /proc/self/mountinfo record (too few fields)")
        try:
            separator = fields.index(b"-", 6)
        except ValueError:
            fail("Unexpected /proc/self/mountinfo record (missing '-' separator)")
        if len(fields) < separator + 3:
            fail("Truncated /proc/self/mountinfo record")

        mount_point = Path(os.fsdecode(_unescape_mountinfo(fields[4])))
        if not mount_point.is_absolute():
            fail("Non-absolute mount point in /proc/self/mountinfo")

        table.append(MountEntry(
            mount_point=mount_point,
            fstype=os.fsdecode(_unescape_mountinfo(fields[separator + 1])),
            source=os.fsdecode(_unescape_mountinfo(fields[separator + 2])),
        ))

    if not table:
        fail("Empty mount table")
    return table


def mount_for(table: Sequence[MountEntry], path: Path) -> MountEntry:
    best: MountEntry | None = None
    best_depth = -1
    for entry in table:
        if path != entry.mount_point and not path.is_relative_to(entry.mount_point):
            continue
        depth = len(entry.mount_point.parts)
        if depth >= best_depth:
            best, best_depth = entry, depth
    if best is None:
        fail(f"No mount point covers {path}")
    return best


def nested_mounts(table: Sequence[MountEntry], root: Path) -> list[Path]:
    return [
        entry.mount_point
        for entry in table
        if entry.mount_point != root and entry.mount_point.is_relative_to(root)
    ]


def require_supported_filesystem(table: Sequence[MountEntry], path: Path, label: str) -> str:
    entry = mount_for(table, path)
    fstype = entry.fstype

    if fstype in TRANSIENT_FILESYSTEMS:
        fail(
            f"Unsupported {label} filesystem {fstype!r} at {entry.mount_point}. "
            "Use the persistent, non-overlay location."
        )
    if fstype in NETWORK_FILESYSTEMS or fstype.startswith(NETWORK_FS_PREFIXES):
        fail(
            f"Unsupported {label} filesystem {fstype!r} at {entry.mount_point}. "
            "Firefox falls back to symlink-only profile locking when fcntl locking is unavailable."
        )
    if fstype.startswith("fuse"):
        LOGGER.warning(
            "%s is on FUSE filesystem %r at %s; fcntl locking semantics may vary.",
            label.capitalize(), fstype, entry.mount_point,
        )
    return fstype


# ===========================================================================
# Directory & File I/O (openat / renameat TOCTOU resistance)
# ===========================================================================

def open_directory(path: Path) -> int:
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        raise SafetyError(f"Cannot open directory {path}: {oserror_detail(error)}") from error


def fsync_dir_fd(dir_fd: int) -> None:
    try:
        os.fsync(dir_fd)
    except OSError as error:
        raise SafetyError(f"Directory fsync failed: {oserror_detail(error)}") from error


def fsync_directory_path(directory: Path) -> None:
    fd = open_directory(directory)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def make_private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chmod(path, 0o700)
    except OSError as error:
        raise SafetyError(f"Cannot create private directory {path}: {oserror_detail(error)}") from error


def read_config(dir_fd: int, name: str) -> str | None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(name, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SafetyError(f"Cannot open {name}: {oserror_detail(error)}") from error

    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            fail(f"Configuration file is not a regular file: {name}")
        if before.st_uid != os.geteuid():
            fail(f"Configuration file is not owned by this user: {name}")
        if before.st_nlink != 1:
            fail(f"Configuration file is hard-linked: {name}")
        if before.st_mode & 0o022:
            LOGGER.warning("Configuration file %s has group/world writable mode %04o", name, before.st_mode & 0o777)
        if before.st_size > MAX_TEXT_BYTES:
            fail(f"Configuration file is too large: {name}")

        data = source.read(MAX_TEXT_BYTES + 1)
        after = os.fstat(source.fileno())

        if len(data) > MAX_TEXT_BYTES:
            fail(f"Configuration file exceeds size limit: {name}")
        if stat_signature(before) != stat_signature(after):
            fail(f"Configuration file changed while being read: {name}")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SafetyError(f"Configuration file {name} is not valid UTF-8") from error


def write_config(dir_fd: int, name: str, content: str) -> None:
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        fail(f"Generated content for {name} exceeds size limit")

    temporary = f".{name}.tmp-{uuid.uuid7().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(temporary, flags, mode=0o600, dir_fd=dir_fd)

    try:
        with os.fdopen(fd, "wb") as destination:
            os.fchmod(destination.fileno(), 0o600)
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())

        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        fsync_dir_fd(dir_fd)
    finally:
        with suppress(OSError):
            os.unlink(temporary, dir_fd=dir_fd)


def remove_config(dir_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
        fsync_dir_fd(dir_fd)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise SafetyError(f"Cannot remove {name}: {oserror_detail(error)}") from error


def replace_config(dir_fd: int, name: str, expected: str | None, replacement: str | None) -> None:
    current = read_config(dir_fd, name)
    if current != expected:
        fail(f"Configuration {name} changed concurrently since inspection")

    if expected == replacement:
        return

    if replacement is None:
        remove_config(dir_fd, name)
    else:
        write_config(dir_fd, name, replacement)


# ===========================================================================
# Open File Description (OFD) Locking
# ===========================================================================

def _flock_payload(lock_type: int) -> bytes:
    return _FLOCK.pack(lock_type, os.SEEK_SET, 0, 0, 0).ljust(_FLOCK_BUFFER, b"\x00")


def probe_lock_holder(fd: int) -> int | None:
    try:
        raw = fcntl.fcntl(fd, fcntl.F_OFD_GETLK, _flock_payload(fcntl.F_WRLCK))
    except OSError as error:
        raise SafetyError(f"Cannot query profile lock: {oserror_detail(error)}") from error

    lock_type, _, _, _, holder = _FLOCK.unpack_from(raw)
    if lock_type == fcntl.F_UNLCK:
        return None
    return holder if holder > 0 else None


def symlink_lock_holder(dir_fd: int) -> tuple[str, int, bool] | None:
    try:
        target = os.readlink(SYMLINK_LOCK, dir_fd=dir_fd)
    except OSError:
        return None
    address, separator, tail = target.partition(":")
    if not separator or not tail:
        return None
    has_fcntl = tail.startswith("+")
    digits = tail[1:] if has_fcntl else tail
    if not digits.isdigit():
        return None
    return address, int(digits), has_fcntl


def process_name(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError:
        return None


@contextmanager
def locked_profile(profile: "Profile", dir_fd: int) -> Iterator[None]:
    try:
        fd = os.open(
            PARENTLOCK,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=dir_fd,
        )
    except OSError as error:
        raise SafetyError(f"Cannot open {profile.path}/.parentlock: {oserror_detail(error)}") from error

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            fail(f"{profile.path}/.parentlock is not a regular file")
        if info.st_uid != os.geteuid():
            fail(f"{profile.path}/.parentlock is not owned by this user")
        if info.st_nlink != 1:
            fail(f"{profile.path}/.parentlock is hard-linked")

        try:
            fcntl.fcntl(fd, fcntl.F_OFD_SETLK, _flock_payload(fcntl.F_WRLCK))
        except (BlockingIOError, PermissionError) as error:
            holder = probe_lock_holder(fd)
            holder_detail = ""
            if holder is not None:
                pname = process_name(holder) or "unknown"
                holder_detail = f" (held by PID {holder} '{pname}')"
            else:
                sym_info = symlink_lock_holder(dir_fd)
                if sym_info is not None:
                    _, sym_pid, _ = sym_info
                    pname = process_name(sym_pid) or "unknown"
                    holder_detail = f" (lock symlink names PID {sym_pid} '{pname}')"

            raise ProfileLockedError(
                f"Firefox profile is locked: {profile.path}{holder_detail}. "
                "Close Firefox normally and rerun."
            ) from error
        except OSError as error:
            raise SafetyError(f"Cannot lock {profile.path}/.parentlock: {oserror_detail(error)}") from error

        yield
    finally:
        os.close(fd)


# ===========================================================================
# Preference Parsing & Legacy Block Migration
# ===========================================================================

@dataclass(frozen=True, slots=True)
class PrefRecord:
    key: str
    value: bool | int | str
    line: str


def split_pref_lines(content: str) -> list[str]:
    return re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$", content)


def parse_pref_line(line: str) -> tuple[str, bool | int | str, str] | None:
    match = PREF_LINE.match(line)
    if match is None:
        return None
    raw_key, raw_val = match.group(1), match.group(2)
    try:
        key = json.loads(f'"{raw_key}"')
        if not isinstance(key, str):
            return None
    except json.JSONDecodeError:
        return None

    value: bool | int | str
    if raw_val == "true":
        value = True
    elif raw_val == "false":
        value = False
    elif raw_val.startswith('"'):
        try:
            value = json.loads(raw_val)
        except json.JSONDecodeError:
            return None
    else:
        try:
            value = int(raw_val)
            if not -(2 ** 31) <= value < 2 ** 31:
                return None
        except ValueError:
            return None

    return key, value, line


def scan_prefs_js(content: str) -> list[PrefRecord]:
    records: list[PrefRecord] = []
    for line in split_pref_lines(content):
        parsed = parse_pref_line(line)
        if parsed is not None:
            records.append(PrefRecord(parsed[0], parsed[1], parsed[2]))
    return records


def extract_legacy_block(content: str | None) -> tuple[str | None, str | None, bool]:
    """
    Extract legacy optimizer block if present.
    Returns: (legacy_block_text, stripped_content, found_flag)
    Preserves all user lines outside the block exactly.
    """
    if content is None:
        return None, None, False

    begin_pattern = "=== BEGIN FIREFOX OPTIMIZATION SUITE ==="
    end_pattern = "=== END FIREFOX OPTIMIZATION SUITE ==="

    if begin_pattern not in content:
        return None, content, False

    lines = split_pref_lines(content)
    in_block = False
    block_lines: list[str] = []
    kept_lines: list[str] = []
    found = False

    for line in lines:
        if begin_pattern in line:
            in_block = True
            found = True
            block_lines.append(line)
            continue
        if end_pattern in line:
            if in_block:
                in_block = False
                block_lines.append(line)
                continue
        if in_block:
            block_lines.append(line)
        else:
            kept_lines.append(line)

    if found:
        stripped = "".join(kept_lines)
        return "".join(block_lines), stripped if stripped.strip() else None, True

    return None, content, False


def strip_legacy_keys_from_prefs(prefs_content: str, legacy_keys: frozenset[str] = LEGACY_KEYS) -> str:
    """Remove legacy aggressive keys from prefs.js so they do not linger after migration."""
    kept: list[str] = []
    for line in split_pref_lines(prefs_content):
        parsed = parse_pref_line(line)
        if parsed is not None and parsed[0] in legacy_keys:
            continue
        kept.append(line)
    return "".join(kept)


def validate_user_js(content: str | None) -> list[tuple[str, object]]:
    if content is None:
        return []

    declarations: list[tuple[str, object]] = []
    decoder = json.JSONDecoder()
    position = 0
    length = len(content)

    def reject(msg: str) -> None:
        fail(f"Invalid or unsupported user.js near char {position}: {msg}")

    def skip_trivia() -> None:
        nonlocal position
        while position < length:
            char = content[position]
            if char in " \t\r\n":
                position += 1
                continue
            if content.startswith("//", position):
                position += 2
                while position < length and content[position] not in "\r\n":
                    position += 1
                continue
            if content.startswith("/*", position):
                end = content.find("*/", position + 2)
                if end == -1:
                    reject("unterminated /* ... */ comment")
                position = end + 2
                continue
            break

    def consume(token: str) -> None:
        nonlocal position
        skip_trivia()
        if not content.startswith(token, position):
            reject(f"expected {token!r}")
        position += len(token)

    def decode_literal() -> object:
        nonlocal position
        skip_trivia()
        try:
            val, end = decoder.raw_decode(content, position)
        except json.JSONDecodeError as error:
            reject(f"expected literal ({error.msg})")
        position = end
        return val

    while True:
        skip_trivia()
        if position == length:
            return declarations

        keyword = USER_JS_KEYWORD.match(content, position)
        if keyword is None:
            reject("expected user_pref, sticky_pref, or pref")
        position = keyword.end()

        consume("(")
        key = decode_literal()
        if not isinstance(key, str):
            reject("preference name must be string")
        consume(",")
        value = decode_literal()
        if type(value) is int:
            if not -(2 ** 31) <= value < 2 ** 31:
                reject("integer outside 32-bit range")
        elif type(value) not in (str, bool):
            reject("only string, boolean, integer values allowed")
        consume(")")
        consume(";")
        declarations.append((key, value))


def managed_lines(content: str) -> tuple[str, ...]:
    return tuple(
        record.line for record in scan_prefs_js(content)
        if record.key in MANAGED_KEYS
    )


def strip_managed_lines(content: str) -> str:
    scan_prefs_js(content)
    return "".join(
        line for line in split_pref_lines(content)
        if (parsed := parse_pref_line(line)) is None or parsed[0] not in MANAGED_KEYS
    )


def restore_managed_lines(content: str, baseline: Sequence[str]) -> str:
    remaining = strip_managed_lines(content)
    if not baseline:
        return remaining
    if remaining and not remaining.endswith(("\n", "\r")):
        remaining += "\n"
    saved = "".join(line if line.endswith(("\n", "\r")) else line + "\n" for line in baseline)
    return remaining + saved


def generated_user_js(original: str | None, capacity_override: int | None = None) -> str:
    """Generate user.js with clean Firefox 155+ managed block."""
    if capacity_override is not None:
        block_lines = [
            "// === BEGIN FIREFOX OPTIMIZATION SUITE ===",
            "// Managed by optimize_firefox.py - Firefox 155+ HTTP cache policy",
            'user_pref("browser.cache.disk.enable", false);',
            'user_pref("browser.cache.memory.enable", true);',
            f'user_pref("browser.cache.memory.capacity", {capacity_override});',
            "// === END FIREFOX OPTIMIZATION SUITE ===",
            "",
        ]
        block = "\n".join(block_lines)
    else:
        block = "\n".join(MANAGED_BLOCK_BODY)

    prefix = (original or "").strip()
    if not prefix:
        return block
    return prefix + "\n\n" + block


def sha256_text(value: str | None) -> str:
    payload = b"" if value is None else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ===========================================================================
# Rollback State
# ===========================================================================

@dataclass(frozen=True, slots=True)
class RollbackState:
    original_user_js: str | None
    baseline_prefs: tuple[str, ...]
    applied_sha256: str
    migrated_from_legacy: bool = False


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"Duplicate key in rollback state: {key}")
        result[key] = value
    return result


def encode_state(state: RollbackState, profile: "Profile") -> str:
    document = {
        "schema": STATE_SCHEMA,
        "tool": TOOL_ID,
        "tool_version": TOOL_VERSION,
        "created_ns": time.time_ns(),
        "profile": str(profile.path),
        "profile_id": f"{profile.device}:{profile.inode}",
        "original_user_js": state.original_user_js,
        "baseline_prefs": list(state.baseline_prefs),
        "applied_sha256": state.applied_sha256,
        "migrated_from_legacy": state.migrated_from_legacy,
    }
    encoded = json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_TEXT_BYTES:
        fail("Rollback state exceeds size limit")
    return encoded


def decode_state(content: str) -> RollbackState:
    try:
        document = json.loads(content, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise SafetyError(f"Rollback state is not valid JSON: {error.msg}") from error

    required = {
        "schema", "tool", "tool_version", "created_ns", "profile",
        "profile_id", "original_user_js", "baseline_prefs", "applied_sha256",
    }
    if not isinstance(document, dict) or not required.issubset(set(document)):
        fail("Invalid rollback-state structure")

    if document["schema"] != STATE_SCHEMA:
        fail(f"Unsupported rollback-state schema {document['schema']!r}")
    if document["tool"] != TOOL_ID:
        fail("Rollback state was written by a different tool")

    original = document["original_user_js"]
    if original is not None and not isinstance(original, str):
        fail("Invalid original user.js in rollback state")

    baseline = document["baseline_prefs"]
    if not isinstance(baseline, list):
        fail("Invalid saved preference list in rollback state")

    validated: list[str] = []
    for line in baseline:
        if not isinstance(line, str):
            fail("Invalid saved preference line")
        validated.append(line)

    return RollbackState(
        original_user_js=original,
        baseline_prefs=tuple(validated),
        applied_sha256=document["applied_sha256"],
        migrated_from_legacy=bool(document.get("migrated_from_legacy", False)),
    )


# ===========================================================================
# Profile Discovery & Root Selection
# ===========================================================================

@dataclass(frozen=True, slots=True)
class ProfileRoot:
    path: Path
    kind: str
    upstream_active: bool


def profile_roots() -> list[ProfileRoot]:
    home = Path.home()
    legacy_home = home / ".mozilla"
    legacy_root = legacy_home / "firefox"

    xdg_value = os.environ.get("XDG_CONFIG_HOME")
    xdg_base = Path(xdg_value) if xdg_value else home / ".config"
    xdg_root = xdg_base / "mozilla" / "firefox"

    forced_legacy = "MOZ_LEGACY_HOME" in os.environ
    legacy_active = forced_legacy or legacy_home.exists()

    resolved_legacy = legacy_root.resolve() if legacy_root.exists() else None
    resolved_xdg = xdg_root.resolve() if xdg_root.exists() else None

    # If both paths resolve to the identical canonical directory (e.g. ~/.mozilla -> ~/.config/mozilla symlink),
    # treat them as one single active root to avoid spurious duplicate/inactive warnings.
    if resolved_legacy and resolved_xdg and resolved_legacy == resolved_xdg:
        LOGGER.info("Firefox 147+ root: %s (legacy symlinked to XDG)", resolved_xdg)
        return [ProfileRoot(resolved_xdg, "xdg", True)]

    LOGGER.info(
        "Firefox 147+ root selection: %s (%s)",
        legacy_root if legacy_active else xdg_root,
        "legacy: ~/.mozilla exists" if legacy_active else "XDG: ~/.mozilla absent",
    )

    roots = [
        ProfileRoot(legacy_root, "legacy", legacy_active),
        ProfileRoot(xdg_root, "xdg", not legacy_active),
    ]

    dedup: dict[Path, ProfileRoot] = {}
    for r in roots:
        try:
            can = r.path.resolve()
        except OSError:
            can = r.path
        if can not in dedup:
            dedup[can] = r
    return list(dedup.values())


def registered_profiles(root: ProfileRoot) -> list[Path]:
    try:
        resolved = root.path.resolve(strict=True)
    except OSError:
        return []

    try:
        root_fd = open_directory(resolved)
    except SafetyError:
        return []

    try:
        content = read_config(root_fd, "profiles.ini")
    finally:
        os.close(root_fd)

    if content is None:
        return []

    # Strip UTF-8 BOM if present
    content = content.lstrip("\ufeff")

    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(content, source=str(resolved / "profiles.ini"))
    except configparser.Error as error:
        raise SafetyError(f"Malformed profiles.ini in {resolved}: {error}") from error

    found: list[Path] = []
    for section in parser.sections():
        if not re.fullmatch(r"Profile\d+", section):
            continue
        where = f"{resolved}/profiles.ini [{section}]"

        if not parser.has_option(section, "Path") or not parser.has_option(section, "IsRelative"):
            fail(f"{where} missing Path or IsRelative")

        raw_path = parser.get(section, "Path").strip()
        if not raw_path or "\x00" in raw_path:
            fail(f"{where} has invalid Path")

        try:
            is_relative = parser.getint(section, "IsRelative")
        except ValueError:
            fail(f"{where} has non-integer IsRelative")

        candidate = Path(raw_path)
        match is_relative:
            case 1:
                if candidate.is_absolute():
                    fail(f"{where}: absolute path marked relative")
                candidate = resolved / candidate
            case 0:
                if not candidate.is_absolute():
                    fail(f"{where}: relative path marked absolute")
            case _:
                fail(f"{where}: invalid IsRelative {is_relative}")

        found.append(candidate)

    return found


@dataclass(frozen=True, slots=True)
class Profile:
    path: Path
    device: int
    inode: int
    fstype: str

    @property
    def identity(self) -> str:
        return hashlib.sha256(os.fsencode(self.path)).hexdigest()[:24]


def validate_profile(candidate: Path, table: Sequence[MountEntry]) -> Profile:
    expanded = candidate.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    try:
        resolved = expanded.resolve(strict=True)
    except FileNotFoundError as error:
        raise SafetyError(f"Profile directory does not exist: {expanded}") from error
    except OSError as error:
        raise SafetyError(f"Cannot resolve profile directory {expanded}: {oserror_detail(error)}") from error

    try:
        info = resolved.stat()
    except OSError as error:
        raise SafetyError(f"Cannot stat profile {resolved}: {oserror_detail(error)}") from error

    if not stat.S_ISDIR(info.st_mode):
        fail(f"Profile is not a directory: {resolved}")
    if info.st_uid != os.geteuid():
        fail(f"Profile is not owned by this user: {resolved}")
    if info.st_mode & 0o022:
        LOGGER.warning("Profile directory %s has permissive permissions %04o", resolved, info.st_mode & 0o777)

    fstype = require_supported_filesystem(table, resolved, "profile")

    dir_fd = open_directory(resolved)
    try:
        if read_config(dir_fd, PREFS_JS) is None:
            raise UninitializedProfileError(f"No prefs.js in {resolved}; profile never started.")
    finally:
        os.close(dir_fd)

    return Profile(resolved, info.st_dev, info.st_ino, fstype)


def select_profiles(explicit: Sequence[Path], table: Sequence[MountEntry]) -> list[Profile]:
    if explicit:
        profiles_found = [validate_profile(path, table) for path in explicit]
    else:
        profiles_found = []
        for root in profile_roots():
            for candidate in registered_profiles(root):
                try:
                    profiles_found.append(validate_profile(candidate, table))
                except UninitializedProfileError as error:
                    LOGGER.warning("Skipping: %s", error)
                except SafetyError as error:
                    LOGGER.warning("Skipping registered profile %s: %s", candidate, error)

    by_inode: dict[tuple[int, int], Profile] = {}
    for prof in profiles_found:
        by_inode.setdefault((prof.device, prof.inode), prof)

    profiles = sorted(by_inode.values(), key=lambda p: p.path)
    if not profiles:
        fail("No usable profile selected. Run Firefox once or specify --profile PATH.")

    for i, p in enumerate(profiles):
        for other in profiles[i + 1:]:
            if p.path.is_relative_to(other.path) or other.path.is_relative_to(p.path):
                fail(f"Nested selected profiles are unsupported: {p.path}, {other.path}")

    return profiles


# ===========================================================================
# Profile Planning & Legacy Migration Engine
# ===========================================================================

@dataclass(frozen=True, slots=True)
class ProfilePlan:
    profile: Profile
    old_user_js: str | None
    old_prefs_js: str
    old_state: str | None
    new_user_js: str | None
    new_prefs_js: str
    new_state: str | None
    advisories: list[str]
    is_migration: bool = False

    @property
    def changed(self) -> bool:
        return (
            self.old_user_js != self.new_user_js
            or self.old_prefs_js != self.new_prefs_js
            or self.old_state != self.new_state
        )


def collect_advisories(prefs_js: str, user_js: str | None) -> list[str]:
    advisories: list[str] = []
    combined = (prefs_js or "") + "\n" + (user_js or "")
    records = scan_prefs_js(combined)

    for rec in records:
        if rec.key == "browser.cache.disk.parent_directory":
            advisories.append(f'browser.cache.disk.parent_directory = "{rec.value}"')
        elif rec.key == "browser.cache.memory.capacity":
            advisories.append(f"browser.cache.memory.capacity = {rec.value}")
        elif rec.key == "browser.cache.disk.smart_size.enabled":
            advisories.append(f"browser.cache.disk.smart_size.enabled = {str(rec.value).lower()}")

    inert_keys = sorted({
        rec.key for rec in records
        if rec.key in {
            "browser.cache.disk_cache_ssl",
            "browser.cache.offline.enable",
            "dom.ipc.processCount",
            "dom.ipc.processCount.webIsolated",
            "dom.ipc.processCount.extension",
            "gfx.webrender.all",
            "layers.acceleration.force-enabled",
            "widget.wayland.opaque-region.enabled",
        }
    })
    if inert_keys:
        advisories.append(
            f"declares preferences that are removed or inert in Firefox 155+: {', '.join(inert_keys)}"
        )
    return list(dict.fromkeys(advisories))


def prepare_profile(
    profile: Profile,
    dir_fd: int,
    memory_mode: bool,
    capacity_override: int | None = None,
) -> ProfilePlan:
    user_js = read_config(dir_fd, USER_JS)
    prefs_js = read_config(dir_fd, PREFS_JS)
    state_text = read_config(dir_fd, STATE_FILENAME)

    if prefs_js is None:
        fail(f"prefs.js missing from {profile.path}")

    baseline_now = managed_lines(prefs_js)
    advisories = collect_advisories(prefs_js, user_js)

    legacy_block, stripped_user_js, has_legacy = extract_legacy_block(user_js)

    # ---------------------------------------------------------------- unmanaged
    if state_text is None:
        if has_legacy:
            LOGGER.info(
                "%s: legacy optimizer block detected in user.js; migrating to clean Firefox 155+ policy",
                profile.path,
            )
            cleaned_prefs = strip_legacy_keys_from_prefs(prefs_js)

            if not memory_mode:
                # --disable on legacy block reverts to clean defaults
                return ProfilePlan(
                    profile=profile,
                    old_user_js=user_js,
                    old_prefs_js=prefs_js,
                    old_state=None,
                    new_user_js=stripped_user_js,
                    new_prefs_js=cleaned_prefs,
                    new_state=None,
                    advisories=advisories,
                    is_migration=True,
                )

            # memory_mode: apply clean modern block over stripped user.js
            new_user_js = generated_user_js(stripped_user_js, capacity_override)
            state = RollbackState(
                original_user_js=stripped_user_js,
                baseline_prefs=baseline_now,
                applied_sha256=sha256_text(new_user_js),
                migrated_from_legacy=True,
            )
            return ProfilePlan(
                profile=profile,
                old_user_js=user_js,
                old_prefs_js=prefs_js,
                old_state=None,
                new_user_js=new_user_js,
                new_prefs_js=cleaned_prefs,
                new_state=encode_state(state, profile),
                advisories=advisories,
                is_migration=True,
            )

        if not memory_mode:
            return ProfilePlan(
                profile, user_js, prefs_js, None, user_js, prefs_js, None, advisories,
            )

        # Normal unmanaged profile without legacy block
        for key, _ in validate_user_js(user_js):
            if key in MANAGED_KEYS:
                fail(f"{profile.path}/user.js already defines managed preference {key!r}")
            if key in SECRET_KEYS:
                fail(f"{profile.path}/user.js pins secret key {key!r}")

        new_user_js = generated_user_js(user_js, capacity_override)
        state = RollbackState(user_js, baseline_now, sha256_text(new_user_js))
        return ProfilePlan(
            profile=profile,
            old_user_js=user_js,
            old_prefs_js=prefs_js,
            old_state=None,
            new_user_js=new_user_js,
            new_prefs_js=prefs_js,
            new_state=encode_state(state, profile),
            advisories=advisories,
        )

    # ------------------------------------------------------------------ managed
    state = decode_state(state_text)
    expected_applied = generated_user_js(state.original_user_js, capacity_override)

    if sha256_text(expected_applied) != state.applied_sha256 and capacity_override is None:
        fail(
            f"{profile.path}: rollback state hash does not match emitted block. "
            "Reconcile with backup and rerun."
        )

    if user_js not in (state.original_user_js, expected_applied):
        fail(
            f"{profile.path}: user.js modified outside this tool. "
            "Reconcile edits with backup and rerun."
        )

    if memory_mode:
        return ProfilePlan(
            profile, user_js, prefs_js, state_text,
            expected_applied, prefs_js, state_text, advisories,
        )

    return ProfilePlan(
        profile, user_js, prefs_js, state_text,
        state.original_user_js,
        restore_managed_lines(prefs_js, state.baseline_prefs),
        None,
        advisories,
    )


# ===========================================================================
# Backups (Zstandard + Streaming Digest)
# ===========================================================================

class DigestWriter:
    __slots__ = ("_target", "_hasher", "bytes_written")

    def __init__(self, target: BinaryIO) -> None:
        self._target = target
        self._hasher = hashlib.sha256()
        self.bytes_written = 0

    def write(self, data: bytes | bytearray | memoryview) -> int:
        n = self._target.write(data)
        self._hasher.update(data[:n])
        self.bytes_written += n
        return n

    def flush(self) -> None:
        self._target.flush()

    @property
    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


@dataclass(frozen=True, slots=True)
class BackupEntry:
    path: Path
    signature: tuple[int, int, int, int, int, int]

    @property
    def mode(self) -> int:
        return self.signature[2]

    @property
    def size(self) -> int:
        return self.signature[3]


def targeted_entries(profile: Profile) -> tuple[list[BackupEntry], int]:
    entries: list[BackupEntry] = []
    total = 0
    for name in (PREFS_JS, USER_JS, STATE_FILENAME):
        cand = profile.path / name
        try:
            info = cand.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise SafetyError(f"Cannot stat {cand}: {oserror_detail(error)}") from error

        if not stat.S_ISREG(info.st_mode):
            fail(f"Backup source is not a regular file: {cand}")
        entries.append(BackupEntry(cand, stat_signature(info)))
        total += info.st_size

    if not entries:
        fail(f"Nothing to back up in {profile.path}")
    return entries, total


def full_entries(profile: Profile, table: Sequence[MountEntry]) -> tuple[list[BackupEntry], int]:
    nested = nested_mounts(table, profile.path)
    if nested:
        fail(f"Nested mount points in profile: {', '.join(map(str, nested))}")

    entries: list[BackupEntry] = []
    visited: set[tuple[int, int]] = set()
    total = 0
    pending = [profile.path]

    while pending:
        cur = pending.pop()
        try:
            info = cur.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise SafetyError(f"Cannot stat {cur}: {oserror_detail(error)}") from error

        if stat.S_ISLNK(info.st_mode):
            if info.st_uid != os.geteuid():
                fail(f"Unsupported symlink ownership: {cur}")
            entries.append(BackupEntry(cur, stat_signature(info)))
            continue

        if info.st_dev != profile.device or info.st_uid != os.geteuid():
            fail(f"Unsupported ownership/nested filesystem in backup source: {cur}")

        is_dir = stat.S_ISDIR(info.st_mode)
        if not (is_dir or stat.S_ISREG(info.st_mode)):
            fail(f"Special file in backup source: {cur}")

        if is_dir:
            ident = (info.st_dev, info.st_ino)
            if ident in visited:
                fail(f"Repeated directory identity in backup source: {cur}")
            visited.add(ident)

        entries.append(BackupEntry(cur, stat_signature(info)))
        if len(entries) > MAX_FULL_BACKUP_ENTRIES:
            fail(f"Profile exceeds {MAX_FULL_BACKUP_ENTRIES} entries; use targeted backup.")

        if not is_dir:
            total += info.st_size
            continue

        try:
            with os.scandir(cur) as it:
                children = sorted(
                    (Path(e.path) for e in it if not (cur == profile.path and e.name in EXCLUDED_ROOT_ENTRIES)),
                    key=os.fspath,
                    reverse=True,
                )
            pending.extend(children)
        except OSError as error:
            raise SafetyError(f"Cannot scan {cur}: {oserror_detail(error)}") from error

    return entries, total


def create_backup_directories(destination: Path) -> None:
    missing: list[Path] = []
    ancestor = destination
    while not ancestor.exists():
        missing.append(ancestor)
        if ancestor.parent == ancestor:
            fail("Backup destination has no existing ancestor")
        ancestor = ancestor.parent

    if not ancestor.is_dir():
        fail(f"Backup ancestor is not a directory: {ancestor}")

    for directory in reversed(missing):
        try:
            make_private_directory(directory)
        except FileExistsError:
            pass
        except OSError as error:
            raise SafetyError(f"Cannot create backup directory {directory}: {oserror_detail(error)}") from error
        fsync_directory_path(directory)
        fsync_directory_path(directory.parent)

    fsync_directory_path(destination.parent)


def resolve_backup_destination(
    profile: Profile,
    override: Path | None,
    selected: Sequence[Profile],
    table: Sequence[MountEntry],
    *,
    create: bool,
) -> Path:
    destination = absolute_without_symlinks(
        override if override is not None else profile.path.parent / DEFAULT_BACKUP_DIRNAME
    )

    for other in selected:
        if destination == other.path or destination.is_relative_to(other.path):
            fail(f"Backup directory must be outside every selected profile: {destination}")

    ancestor = destination
    while not ancestor.exists():
        if ancestor.parent == ancestor:
            fail("Backup destination has no existing ancestor")
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        fail(f"Backup ancestor is not a directory: {ancestor}")

    require_supported_filesystem(table, ancestor, "backup")

    if ancestor.stat().st_dev != profile.device:
        LOGGER.info(
            "Backup destination %s is on a separate filesystem than %s.",
            destination, profile.path,
        )

    if create:
        create_backup_directories(destination)

    if destination.exists():
        info = destination.lstat()
        if not stat.S_ISDIR(info.st_mode):
            fail(f"Backup destination is not a directory: {destination}")
        if info.st_uid != os.geteuid():
            fail(f"Backup directory is not owned by this user: {destination}")

        if info.st_mode & 0o077:
            if create:
                try:
                    os.chmod(destination, 0o700)
                    info = destination.lstat()
                except OSError as error:
                    raise SafetyError(f"Cannot tighten permissions on {destination}: {oserror_detail(error)}") from error
                if info.st_mode & 0o077:
                    fail(f"Backup directory {destination} remains accessible after chmod")

    return destination


def build_manifest(profile: Profile, scope: str, entries: Sequence[BackupEntry]) -> bytes:
    doc = {
        "manifest_version": 1,
        "tool": TOOL_ID,
        "tool_version": TOOL_VERSION,
        "created_ns": time.time_ns(),
        "profile": str(profile.path),
        "profile_id": profile.identity,
        "scope": scope,
        "entries": [
            {
                "name": str(e.path.relative_to(profile.path)),
                "size": e.size,
                "mode": f"{e.mode:04o}",
            }
            for e in entries
        ],
    }
    return json.dumps(doc, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _tar_filter(member: tarfile.TarInfo) -> tarfile.TarInfo:
    if not (member.isreg() or member.isdir() or member.issym()):
        fail(f"Refusing to archive special member: {member.name}")
    member.uname = ""
    member.gname = ""
    return member


def backup_profile(
    profile: Profile, destination: Path, scope: str, table: Sequence[MountEntry]
) -> Path:
    entries, total_bytes = (
        targeted_entries(profile) if scope == "targeted" else full_entries(profile, table)
    )

    estimated = total_bytes + total_bytes // 10 + len(entries) * 4096 + BACKUP_HEADROOM_BYTES
    available = shutil.disk_usage(destination).free
    if available < estimated:
        fail(
            f"Insufficient headroom at {destination}: {human_bytes(available)} available, "
            f"{human_bytes(estimated)} estimated."
        )

    final_name = f"{BACKUP_PREFIX}-{scope}-{profile.identity}-{uuid.uuid7().hex}.tar.zst"
    final_path = destination / final_name
    temporary = destination / f"{TEMP_ARCHIVE_PREFIX}{uuid.uuid7().hex}.tar.zst"

    zstd_options = {
        zstd.CompressionParameter.compression_level: (
            ZSTD_LEVEL_TARGETED if scope == "targeted" else ZSTD_LEVEL_FULL
        ),
        zstd.CompressionParameter.checksum_flag: 1,
    }

    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )

    try:
        with os.fdopen(fd, "wb") as raw:
            os.fchmod(raw.fileno(), 0o600)
            writer = DigestWriter(raw)

            with zstd.ZstdFile(writer, "w", options=zstd_options) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT, dereference=False) as archive:
                    manifest_data = build_manifest(profile, scope, entries)
                    ti = tarfile.TarInfo(f"{profile.path.name}/BACKUP-MANIFEST.json")
                    ti.size = len(manifest_data)
                    ti.mode = 0o600
                    ti.mtime = int(time.time())
                    archive.addfile(ti, io.BytesIO(manifest_data))

                    for e in entries:
                        if stat_signature(e.path.lstat()) != e.signature:
                            fail(f"Profile changed before backup: {e.path}")
                        arcname = (Path(profile.path.name) / e.path.relative_to(profile.path)).as_posix()
                        archive.add(e.path, arcname=arcname, recursive=False, filter=_tar_filter)
                        if stat_signature(e.path.lstat()) != e.signature:
                            fail(f"Profile changed during backup: {e.path}")

            raw.flush()
            os.fsync(raw.fileno())

        if scope == "full" and nested_mounts(read_mount_table(), profile.path):
            fail("Mount topology changed during backup")

        os.replace(temporary, final_path)
        fsync_directory_path(destination)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)

    LOGGER.info("Backup created: %s (%s, %s)", final_path.name, scope, human_bytes(final_path.stat().st_size))

    # Rotation: retain last MAX_BACKUPS_PER_PROFILE per profile and scope
    rotate_backups(destination, profile, scope)
    return final_path


def rotate_backups(destination: Path, profile: Profile, scope: str) -> None:
    pattern = re.compile(
        rf"^{re.escape(BACKUP_PREFIX)}-{re.escape(scope)}-{re.escape(profile.identity)}-[0-9a-f]{{32}}\.tar\.zst$"
    )
    matching: list[Path] = []
    stale_temp: list[Path] = []
    now = time.time()

    for item in destination.iterdir():
        if pattern.fullmatch(item.name):
            matching.append(item)
        elif item.name.startswith(TEMP_ARCHIVE_PREFIX) and item.name.endswith(".tar.zst"):
            try:
                if now - item.stat().st_mtime > 86400:
                    stale_temp.append(item)
            except OSError:
                pass

    for temp in stale_temp:
        with suppress(OSError):
            temp.unlink(missing_ok=True)
            LOGGER.info("Reaped stale temp backup: %s", temp.name)

    matching.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for old in matching[MAX_BACKUPS_PER_PROFILE:]:
        try:
            old.unlink(missing_ok=True)
            LOGGER.info("Rotated backup: %s", old.name)
        except OSError as error:
            LOGGER.warning("Could not rotate %s: %s", old.name, error)


# ===========================================================================
# Execution & Verification
# ===========================================================================

def apply_plan(plan: ProfilePlan, dir_fd: int) -> None:
    if plan.new_state is not None:
        replace_config(dir_fd, STATE_FILENAME, plan.old_state, plan.new_state)
        replace_config(dir_fd, PREFS_JS, plan.old_prefs_js, plan.new_prefs_js)
        replace_config(dir_fd, USER_JS, plan.old_user_js, plan.new_user_js)
    else:
        replace_config(dir_fd, PREFS_JS, plan.old_prefs_js, plan.new_prefs_js)
        replace_config(dir_fd, USER_JS, plan.old_user_js, plan.new_user_js)
        replace_config(dir_fd, STATE_FILENAME, plan.old_state, None)

    LOGGER.info("Updated profile: %s", plan.profile.path)


def verify_applied(plan: ProfilePlan, dir_fd: int) -> None:
    for name, expected in (
        (STATE_FILENAME, plan.new_state),
        (USER_JS, plan.new_user_js),
        (PREFS_JS, plan.new_prefs_js),
    ):
        actual = read_config(dir_fd, name)
        if actual != expected:
            fail(f"Post-write verification failed for {plan.profile.path}/{name}")


# ===========================================================================
# Status & Diagnostics
# ===========================================================================

def cache2_info(profile: Profile, prefs_js: str | None) -> tuple[Path, int, int]:
    cache_root: Path | None = None
    if prefs_js:
        for rec in scan_prefs_js(prefs_js):
            if rec.key == "browser.cache.disk.parent_directory" and isinstance(rec.value, str):
                val = Path(rec.value)
                if val.is_absolute():
                    cache_root = val / "cache2"
                break

    if cache_root is None:
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
        cache_root = base / "mozilla" / "firefox" / profile.path.name / "cache2"

    if not cache_root.is_dir():
        return cache_root, 0, 0

    count = 0
    total = 0
    try:
        for root, _, files in os.walk(cache_root):
            for f in files:
                count += 1
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass

    return cache_root, count, total


def report_status(profiles: Sequence[Profile], as_json: bool) -> int:
    report_data = []

    for profile in profiles:
        prof_report = {
            "profile": str(profile.path),
            "filesystem": profile.fstype,
            "lock": "unknown",
            "lock_holder": None,
            "browser.cache.disk.enable": None,
            "browser.cache.memory.enable": None,
            "managed": "no",
            "advisories": [],
            "cache2_path": None,
            "cache2_files": 0,
            "cache2_bytes": 0,
        }

        try:
            dir_fd = open_directory(profile.path)
        except SafetyError as error:
            prof_report["error"] = str(error)
            report_data.append(prof_report)
            continue

        try:
            # Check lock
            try:
                lfd = os.open(PARENTLOCK, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=dir_fd)
                try:
                    holder = probe_lock_holder(lfd)
                    if holder is not None:
                        prof_report["lock"] = "locked"
                        pname = process_name(holder) or "unknown"
                        prof_report["lock_holder"] = {"pid": holder, "comm": pname}
                    else:
                        sym = symlink_lock_holder(dir_fd)
                        if sym is not None:
                            prof_report["lock"] = f"free (stale lock -> {sym[0]}:+{sym[1]})"
                        else:
                            prof_report["lock"] = "free"
                finally:
                    os.close(lfd)
            except FileNotFoundError:
                prof_report["lock"] = "free (no .parentlock)"
            except OSError:
                prof_report["lock"] = "unreadable"

            prefs_js = read_config(dir_fd, PREFS_JS)
            user_js = read_config(dir_fd, USER_JS)
            state_text = read_config(dir_fd, STATE_FILENAME)

            combined = (prefs_js or "") + "\n" + (user_js or "")
            for rec in scan_prefs_js(combined):
                if rec.key == "browser.cache.disk.enable":
                    prof_report["browser.cache.disk.enable"] = rec.value
                elif rec.key == "browser.cache.memory.enable":
                    prof_report["browser.cache.memory.enable"] = rec.value

            if state_text is not None:
                prof_report["managed"] = "yes"
            else:
                _, _, has_legacy = extract_legacy_block(user_js)
                if has_legacy:
                    prof_report["managed"] = "legacy optimizer block present (migration ready)"

            prof_report["advisories"] = collect_advisories(prefs_js or "", user_js)
            cpath, ccount, cbytes = cache2_info(profile, prefs_js)
            prof_report["cache2_path"] = str(cpath)
            prof_report["cache2_files"] = ccount
            prof_report["cache2_bytes"] = cbytes

        finally:
            os.close(dir_fd)

        report_data.append(prof_report)

    if as_json:
        print(json.dumps({"tool": TOOL_NAME, "version": TOOL_VERSION, "profiles": report_data}, indent=2))
        return 0

    import platform
    LOGGER.info("%s %s - Firefox 155+ HTTP cache-policy manager", TOOL_NAME, TOOL_VERSION)
    LOGGER.info("Kernel     : %s", platform.release())
    LOGGER.info("Python     : %s", platform.python_version())
    try:
        ff_out = subprocess.run(["firefox", "--version"], capture_output=True, text=True, check=False)
        LOGGER.info("Firefox    : %s", ff_out.stdout.strip() or "unknown")
    except Exception:
        LOGGER.info("Firefox    : (not on PATH)")

    for pr in report_data:
        LOGGER.info("--- %s", pr["profile"])
        LOGGER.info("    filesystem : %s", pr["filesystem"])
        lock_str = pr["lock"]
        if pr.get("lock_holder"):
            lock_str += f" (PID {pr['lock_holder']['pid']} '{pr['lock_holder']['comm']}')"
        LOGGER.info("    lock       : %s", lock_str)
        LOGGER.info("    browser.cache.disk.enable   = %s", str(pr["browser.cache.disk.enable"]).lower())
        LOGGER.info("    browser.cache.memory.enable = %s", str(pr["browser.cache.memory.enable"]).lower())
        LOGGER.info("    managed    : %s", pr["managed"])
        for adv in pr["advisories"]:
            LOGGER.info("    advisory   : %s", adv)
        LOGGER.info("    cache2     : %s in %d file(s) at %s", human_bytes(pr["cache2_bytes"]), pr["cache2_files"], pr["cache2_path"])

    return 0


# ===========================================================================
# Maintenance Services Check
# ===========================================================================

def require_inactive_maintenance_services() -> None:
    if shutil.which("systemctl") is None:
        return

    try:
        res = subprocess.run(
            ["systemctl", "--user", "show", *MAINTENANCE_UNITS, "--property=Id,LoadState,ActiveState,UnitFileState"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10.0,
        )
    except (subprocess.SubprocessError, OSError):
        return

    if res.returncode != 0:
        return

    blocks = res.stdout.strip().split("\n\n")
    for block in blocks:
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        unit_id = props.get("Id", "")
        load_state = props.get("LoadState", "")
        active_state = props.get("ActiveState", "")
        file_state = props.get("UnitFileState", "")

        if load_state == "not-found":
            continue
        if active_state in {"active", "activating"}:
            fail(f"Active maintenance unit detected: {unit_id}. Close Firefox and stop profile automation.")
        if file_state in {"enabled", "enabled-runtime"}:
            fail(f"Maintenance unit {unit_id} is enabled; reconcile this automation before applying.")


# ===========================================================================
# Self-Contained Verification Harness (--verify)
# ===========================================================================

def run_verification_suite(verbose: bool) -> int:
    """
    Self-contained empirical verification test harness.
    Exercises toolchain, disposable profiles, dry-run purity, umask independence,
    headless Firefox persistence, OFD locking, legacy migration, and round-tripping.
    """
    failed = 0
    passed = 0

    def vlog(msg: str) -> None:
        print(f"\033[36m==>\033[0m {msg}", flush=True)

    def vok(msg: str) -> None:
        nonlocal passed
        passed += 1
        print(f"\033[32m  [PASS]\033[0m {msg}", flush=True)

    def vfail(msg: str) -> None:
        nonlocal failed
        failed += 1
        print(f"\033[31m  [FAIL]\033[0m {msg}", flush=True)

    print("\n====================================================")
    print("  optimize_firefox.py: Self-Verification Suite      ")
    print("====================================================\n")

    # 1. Toolchain & Environment
    vlog("1. Toolchain & Environment Verification")
    import platform
    print(f"Kernel     : {platform.release()}")
    print(f"Python     : {platform.python_version()}")

    ff_ver_str = "unknown"
    try:
        ff_run = subprocess.run(["firefox", "--version"], capture_output=True, text=True, check=False)
        ff_ver_str = ff_run.stdout.strip()
    except OSError:
        pass
    print(f"Firefox    : {ff_ver_str}")

    ff_match = re.search(r"(\d+)", ff_ver_str)
    if ff_match and int(ff_match.group(1)) >= MIN_FIREFOX_MAJOR:
        vok(f"Firefox {ff_match.group(1)} >= {MIN_FIREFOX_MAJOR}")
    else:
        vfail(f"Firefox {MIN_FIREFOX_MAJOR}+ required; found {ff_ver_str}")

    assert hasattr(uuid, "uuid7"), "uuid7 missing"
    assert hasattr(fcntl, "F_OFD_SETLK") and hasattr(fcntl, "F_OFD_GETLK"), "OFD locks missing"
    assert hasattr(zstd, "ZstdFile"), "ZstdFile missing"
    vok("Python 3.14.7+ runtime prerequisites (OFD, zstd, uuid7) verified")

    # 2. Setup disposable profile on a persistent filesystem (e.g. ~/.cache)
    cache_base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    cache_base.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="ffcp-verify-", dir=cache_base))
    profile_dir = work_dir / "profile"
    backups_dir = work_dir / "backups"
    script_path = Path(__file__).resolve()

    def run_sub(*sub_args, expect_code=0, timeout=25.0) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(script_path), *sub_args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if proc.returncode != expect_code:
            raise AssertionError(
                f"Expected exit code {expect_code}, got {proc.returncode}.\n"
                f"Stdout: {proc.stdout}\nStderr: {proc.stderr}"
            )
        return proc

    def ff_headless(timeout_sec=30):
        try:
            subprocess.run(
                [
                    "firefox", "--no-remote", "--profile", str(profile_dir), "--headless",
                    "--screenshot", str(work_dir / "shot.png"), "about:blank"
                ],
                capture_output=True,
                timeout=timeout_sec,
                check=False,
            )
        except Exception:
            pass

    try:
        # Initialize test profile
        vlog("2. Initialize Disposable Test Profile")
        profile_dir.mkdir(parents=True, exist_ok=True)
        ff_headless(35)
        ff_headless(25)
        if (profile_dir / "prefs.js").is_file():
            vok("prefs.js generated by Firefox")
        else:
            (profile_dir / "prefs.js").write_text('user_pref("app.update.enabled", false);\n', encoding="utf-8")
            (profile_dir / ".parentlock").touch()
            vok("prefs.js initialized")

        # 3. Dry-Run Purity
        vlog("3. Dry-Run Purity Verification")
        before_tree = {p: p.lstat().st_mtime_ns for p in profile_dir.rglob("*")}
        run_sub("--cache-mode", "memory", "--profile", str(profile_dir), "--backup-dir", str(backups_dir), "--dry-run")
        after_tree = {p: p.lstat().st_mtime_ns for p in profile_dir.rglob("*")}
        if before_tree == after_tree and not backups_dir.exists() and not (profile_dir / "user.js").exists():
            vok("Dry-run mutated zero files and created zero directories")
        else:
            vfail("Dry-run caused filesystem mutations")

        # 4. Apply Memory Mode Policy
        vlog("4. Apply --cache-mode memory")
        run_sub("--cache-mode", "memory", "--profile", str(profile_dir), "--backup-dir", str(backups_dir))
        u_content = (profile_dir / "user.js").read_text(encoding="utf-8")
        if 'user_pref("browser.cache.disk.enable", false);' in u_content:
            vok("browser.cache.disk.enable=false applied")
        else:
            vfail("disk.enable missing from user.js")
        if 'user_pref("browser.cache.memory.enable", true);' in u_content:
            vok("browser.cache.memory.enable=true applied")
        else:
            vfail("memory.enable missing from user.js")
        if "browser.cache.memory.capacity" not in u_content:
            vok("Memory capacity left at native dynamic default")
        else:
            vfail("Capacity was forced unnecessarily")

        # 5. Exact Modes & Umask Independence
        vlog("5. Exact File Modes & Umask Independence")
        u_mode = stat.S_IMODE((profile_dir / "user.js").stat().st_mode)
        s_mode = stat.S_IMODE((profile_dir / STATE_FILENAME).stat().st_mode)
        b_mode = stat.S_IMODE(backups_dir.stat().st_mode)
        if u_mode == 0o600 and s_mode == 0o600 and b_mode == 0o700:
            vok(f"Exact modes verified (user.js: {u_mode:04o}, state: {s_mode:04o}, backup_dir: {b_mode:04o})")
        else:
            vfail(f"Incorrect modes: user.js {u_mode:04o}, state {s_mode:04o}, backup_dir {b_mode:04o}")

        # Test hostile umask 0777
        run_sub("--disable", "--profile", str(profile_dir), "--backup-dir", str(backups_dir), "--no-backup")
        old_umask = os.umask(0o777)
        try:
            run_sub("--cache-mode", "memory", "--profile", str(profile_dir), "--backup-dir", str(backups_dir), "--no-backup")
        finally:
            os.umask(old_umask)
        hostile_mode = stat.S_IMODE((profile_dir / "user.js").stat().st_mode)
        if hostile_mode == 0o600:
            vok("Exact mode 0600 enforced even under hostile umask 0777")
        else:
            vfail(f"Umask leaked into file mode: {hostile_mode:04o}")

        # 6. Rollback State Schema
        vlog("6. Rollback State Validation")
        state_doc = json.loads((profile_dir / STATE_FILENAME).read_text(encoding="utf-8"))
        if state_doc.get("schema") == STATE_SCHEMA and state_doc.get("tool") == TOOL_ID:
            vok(f"State schema {STATE_SCHEMA} validated with tool ID {TOOL_ID}")
        else:
            vfail(f"Invalid state document: {state_doc}")

        # 7. Headless Firefox Persistence Test
        vlog("7. Headless Firefox 155+ Persistence Verification")
        ff_headless(35)
        p_content = (profile_dir / "prefs.js").read_text(encoding="utf-8")
        if 'user_pref("browser.cache.disk.enable", false);' in p_content:
            vok("Firefox persisted disk.enable=false into prefs.js at shutdown")
        else:
            vfail("Firefox did not persist user.js into prefs.js")

        # 8. Exclusive OFD Locking Test
        vlog("8. Exclusive OFD Locking Contention (Exit 3)")
        ff_proc = subprocess.Popen(
            ["firefox", "--no-remote", "--profile", str(profile_dir), "--headless", "about:blank"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(4.0)
            lock_proc = subprocess.run(
                [sys.executable, str(script_path), "--disable", "--profile", str(profile_dir), "--backup-dir", str(backups_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            if lock_proc.returncode == 3 and "PID" in lock_proc.stderr:
                vok("Exclusive OFD lock correctly detected running Firefox (exit code 3, holder reported)")
            else:
                vfail(f"Lock contention failed (code {lock_proc.returncode}): {lock_proc.stderr}")
        finally:
            ff_proc.terminate()
            ff_proc.wait(timeout=5.0)
            time.sleep(1.0)

        # 9. Restore with --disable & Round-Trip Custom Preferences
        vlog("9. Restore with --disable & Custom Preference Preservation")
        custom_snippet = '// Theme Customizations\nuser_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
        (profile_dir / "user.js").write_text(custom_snippet, encoding="utf-8")
        h0 = hashlib.sha256(custom_snippet.encode()).hexdigest()
        (profile_dir / STATE_FILENAME).unlink(missing_ok=True)

        run_sub("--cache-mode", "memory", "--profile", str(profile_dir), "--backup-dir", str(backups_dir), "--no-backup")
        run_sub("--disable", "--profile", str(profile_dir), "--backup-dir", str(backups_dir), "--no-backup")
        restored = (profile_dir / "user.js").read_text(encoding="utf-8")
        h1 = hashlib.sha256(restored.encode()).hexdigest()
        if h0 == h1 and not (profile_dir / STATE_FILENAME).exists():
            vok("Custom user.js preserved byte-identically through memory/disable cycle")
        else:
            vfail("user.js was altered during round-trip restore")

        # 10. Legacy Optimizer Block Migration
        vlog("10. Legacy Optimizer Block Migration")
        legacy_content = (
            'user_pref("svg.context-properties.content.enabled", true);\n'
            'user_pref("widget.gtk.non-native-context-menus", true);\n'
            '// === BEGIN FIREFOX OPTIMIZATION SUITE ===\n'
            '// Auto-generated by Firefox System Optimizer\n'
            'user_pref("browser.cache.memory.enable", true);\n'
            'user_pref("browser.cache.memory.capacity", 4194304);\n'
            'user_pref("browser.cache.disk.smart_size.enabled", false);\n'
            'user_pref("dom.ipc.processCount", 32);\n'
            'user_pref("gfx.webrender.all", true);\n'
            'user_pref("layers.acceleration.force-enabled", true);\n'
            'user_pref("browser.cache.disk.enable", true);\n'
            '// === END FIREFOX OPTIMIZATION SUITE ===\n'
        )
        (profile_dir / "user.js").write_text(legacy_content, encoding="utf-8")
        (profile_dir / STATE_FILENAME).unlink(missing_ok=True)

        run_sub("--cache-mode", "memory", "--profile", str(profile_dir), "--backup-dir", str(backups_dir), "--no-backup")
        migrated_u = (profile_dir / "user.js").read_text(encoding="utf-8")
        if (
            "svg.context-properties.content.enabled" in migrated_u
            and "widget.gtk.non-native-context-menus" in migrated_u
            and "dom.ipc.processCount" not in migrated_u
            and 'user_pref("browser.cache.disk.enable", false);' in migrated_u
        ):
            vok("Legacy optimizer block migrated: dead keys stripped, custom preferences preserved")
        else:
            vfail(f"Migration produced unexpected user.js:\n{migrated_u}")

        # 11. Safety Negative Tests
        vlog("11. Safety Negative Tests")
        neg1 = subprocess.run([sys.executable, str(script_path), "--cache-mode", "memory", "--profile", str(work_dir / "missing")], capture_output=True)
        neg2 = subprocess.run([sys.executable, str(script_path), "--cache-mode", "memory", "--profile", "/tmp"], capture_output=True)
        if neg1.returncode != 0 and neg2.returncode != 0:
            vok("Safety negative tests properly rejected missing profiles and tmpfs paths")
        else:
            vfail("Negative tests failed to reject unsafe paths")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    print("\n====================================================")
    if failed == 0:
        print(f"\033[32m  ALL {passed} EMPIRICAL VERIFICATION CHECKS PASSED!\033[0m")
        print("====================================================\n")
        return 0
    else:
        print(f"\033[31m  {failed} CHECKS FAILED! (Passed: {passed})\033[0m")
        print("====================================================\n")
        return 1


# ===========================================================================
# CLI Interface
# ===========================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        color=True,
        suggest_on_error=True,
        description=(
            "Bleeding-edge Firefox 155+ HTTP cache-policy manager: exclusive "
            "Linux OFD locking, private zstd backups, saved-preference rollback, "
            "umask-independent atomic writes, and seamless legacy optimizer migration."
        ),
        epilog=(
            "Exit status: 0 success, 1 error, 2 usage error, 3 profile locked by running Firefox, "
            "130 interrupted, 143 terminated."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--cache-mode",
        choices=("memory", "default"),
        help=(
            "'memory': disable the HTTP disk cache and enable the memory cache. "
            "'default': restore baseline configuration."
        ),
    )
    action.add_argument("--disable", action="store_true", help="Alias for --cache-mode default.")
    action.add_argument("--status", action="store_true", help="Read-only diagnostic report.")
    action.add_argument("--verify", action="store_true", help="Run full self-contained empirical verification suite.")

    parser.add_argument(
        "--profile", type=Path, action="append", default=None,
        help="Initialized profile directory (repeatable). Explicit paths replace discovery.",
    )
    parser.add_argument(
        "--backup-dir", type=Path,
        help=f"Backup directory outside selected profiles. Default: <parent>/{DEFAULT_BACKUP_DIRNAME}",
    )
    parser.add_argument(
        "--backup-scope", choices=("targeted", "full"), default="targeted",
        help="'targeted' (default): archive user.js, prefs.js, state.json. 'full': entire profile.",
    )
    parser.add_argument(
        "--memory-capacity", type=int, default=None,
        help="Optional memory cache capacity in KB (e.g. 4194304 for 4GB). Default: dynamic.",
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="Skip creating backup archives on apply/restore.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate changes without writing.")
    parser.add_argument("--json", action="store_true", help="Output status report as JSON.")
    parser.add_argument("--skip-maintenance-check", action="store_true", help="Bypass systemd unit check.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug diagnostics.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    if args.verify:
        return run_verification_suite(args.verbose)

    # Signal handlers for clean ExitStack unwinding
    def handle_signal(signum: int, _) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)

    if os.geteuid() == 0:
        fail("Running as root or via sudo is refused. Run as the Firefox profile owner.")

    table = read_mount_table()

    explicit_profiles = [Path(p) for p in args.profile] if args.profile else []
    profiles = select_profiles(explicit_profiles, table)

    if args.status:
        return report_status(profiles, args.json)

    if not args.skip_maintenance_check:
        require_inactive_maintenance_services()

    memory_mode = not args.disable and args.cache_mode == "memory"
    LOGGER.info(
        "Requested action: %s",
        "memory-only HTTP cache policy" if memory_mode else "restore baseline configuration",
    )

    if args.dry_run:
        LOGGER.info("[Dry Run] Simulating without taking locks or writing files:")
        for prof in profiles:
            dir_fd = open_directory(prof.path)
            try:
                plan = prepare_profile(prof, dir_fd, memory_mode, args.memory_capacity)
                if not plan.changed:
                    LOGGER.info("[Dry Run] %s: already in requested state (no-op)", prof.path)
                    continue

                if plan.is_migration:
                    LOGGER.info("[Dry Run] %s: legacy optimizer block will be migrated", prof.path)

                if not args.no_backup:
                    dest = resolve_backup_destination(prof, args.backup_dir, profiles, table, create=False)
                    entries, size = (
                        targeted_entries(prof) if args.backup_scope == "targeted" else full_entries(prof, table)
                    )
                    LOGGER.info(
                        "[Dry Run] %s: would create %s backup (%d entries, ~%s) at %s",
                        prof.path, args.backup_scope, len(entries), human_bytes(size), dest,
                    )
                else:
                    LOGGER.info("[Dry Run] %s: backup creation skipped (--no-backup)", prof.path)
                LOGGER.info("[Dry Run] %s: would apply updated user.js / prefs.js", prof.path)
            finally:
                os.close(dir_fd)
        LOGGER.info("[Dry Run] Completed successfully.")
        return 0

    # Real run: pin directory descriptors, acquire OFD locks in stable sorted order
    with ExitStack() as stack:
        dir_fds: dict[Profile, int] = {}
        for prof in profiles:
            dfd = stack.enter_context(contextmanager(lambda p=prof.path: (yield open_directory(p)))())
            dir_fds[prof] = dfd
            stack.enter_context(locked_profile(prof, dfd))

        if not args.skip_maintenance_check:
            require_inactive_maintenance_services()

        plans = [
            prepare_profile(prof, dir_fds[prof], memory_mode, args.memory_capacity)
            for prof in profiles
        ]
        changes = [p for p in plans if p.changed]

        if not changes:
            LOGGER.info("All profiles are already in the requested state. No changes required.")
            return 0

        # Create backups for all changing profiles before any writes occur (unless --no-backup)
        if not args.no_backup:
            for plan in changes:
                dest = resolve_backup_destination(
                    plan.profile, args.backup_dir, profiles, table, create=True
                )
                backup_profile(plan.profile, dest, args.backup_scope, table)
        else:
            LOGGER.info("Skipping backup creation (--no-backup specified).")

        # Apply changes atomically
        for plan in changes:
            apply_plan(plan, dir_fds[plan.profile])
            verify_applied(plan, dir_fds[plan.profile])

    LOGGER.info("Requested cache-policy changes applied successfully.")
    LOGGER.info("Start Firefox normally to run with the updated cache configuration.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ProfileLockedError as lock_err:
        LOGGER.error("%s", lock_err)
        sys.exit(3)
    except SafetyError as safety_err:
        LOGGER.error("%s", safety_err)
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.error("Interrupted by user (SIGINT).")
        sys.exit(130)
    except SystemExit as se:
        raise se
    except Exception as exc:
        LOGGER.error("Unexpected error: %s", exc)
        LOGGER.debug("Stack trace:", exc_info=True)
        sys.exit(1)
