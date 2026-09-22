#!/usr/bin/env python3
from __future__ import annotations

import errno
import fcntl
import hashlib
from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

if sys.version_info < (3, 14):
    raise SystemExit("Dusky supervisor requires Python 3.14+")

SCRIPT = Path(__file__).with_name("update_dusky.py").resolve()
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "dusky-updater-supervisor"
KNOWN = STATE / "known_good"
PREVIOUS = STATE / "known_good.previous"
CONTROL = STATE / "control"
MANIFEST = KNOWN / "manifest.json"
ROLLBACK_JOURNAL = STATE / "rollback_pending.json"
REJECTED = STATE / "rejected_candidate.json"
REJECTED_TTL_SEC = 7 * 24 * 3600


def digest(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            return None
    except OSError:
        return None
    h = hashlib.blake2b(digest_size=16)
    try:
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    ensure_private_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def copy_durable(src: Path, dst: Path) -> None:
    st = src.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise RuntimeError(f"known-good bundle member must be a regular file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=False)
    fd = os.open(str(dst), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(dst.parent)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def read_manifest(root: Path = KNOWN) -> dict[str, Any] | None:
    data = read_json(root / "manifest.json")
    if not data or data.get("schema") != 2:
        return None
    files = data.get("files")
    if not isinstance(files, list) or not files:
        return None
    seen: set[str] = set()
    for rec in files:
        if not isinstance(rec, dict):
            return None
        kind = rec.get("kind")
        installed = rec.get("installed")
        saved = rec.get("saved")
        expected = rec.get("digest")
        present = rec.get("present", True)
        if kind not in {"script", "profile", "settings"} or kind in seen:
            return None
        if not isinstance(installed, str) or not installed or not Path(installed).is_absolute():
            return None
        if not isinstance(present, bool):
            return None
        if present:
            if not isinstance(saved, str) or not saved or "/" in saved or "\\" in saved:
                return None
            if not isinstance(expected, str) or not expected:
                return None
            src = root / saved
            if digest(src) != expected:
                return None
        else:
            if kind != "settings" or saved not in ("", None) or expected not in ("", None):
                return None
        seen.add(kind)
    if "script" not in seen or "profile" not in seen:
        return None
    return data


def bundle_valid(root: Path) -> bool:
    return read_manifest(root) is not None


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
        fsync_dir(path.parent)


def recover_supervisor_state() -> None:
    ensure_private_dir(STATE)
    # If publication was interrupted between KNOWN -> PREVIOUS and tmp -> KNOWN,
    # PREVIOUS is a complete durable generation and is preferable to guessing.
    if not bundle_valid(KNOWN) and bundle_valid(PREVIOUS):
        if KNOWN.exists():
            corrupt = STATE / f"known_good.corrupt.{int(time.time())}"
            os.replace(KNOWN, corrupt)
            fsync_dir(STATE)
        os.replace(PREVIOUS, KNOWN)
        fsync_dir(STATE)
    elif bundle_valid(KNOWN) and PREVIOUS.exists():
        _remove_tree(PREVIOUS)

    if ROLLBACK_JOURNAL.exists():
        if not bundle_valid(KNOWN) or not restore_known_good():
            raise RuntimeError(
                f"an interrupted rollback could not be completed; recovery data retained at {KNOWN}"
            )


def _health_members(health: dict[str, Any]) -> list[tuple[str, Path, str | None]]:
    """Validate the worker health bundle and return snapshot members.

    The updater script and active profile are mandatory regular files.

    The settings file is intentionally optional: the worker supports a
    settings-free configuration and reports that state as
    ``settings_digest=None``. Absence is valid only when the pathname truly
    does not exist. An existing non-regular settings object is not equivalent
    to absence and is rejected.

    Validation is race-aware: after lstat() establishes the expected object
    type, digest() reopens and hashes the file. If the object disappears or
    changes type between those operations, digest() returns None and the health
    checkpoint is rejected rather than blessing an ambiguous bundle.
    """
    if health.get("schema") != 1:
        raise RuntimeError("unsupported worker health schema")

    launch_id = health.get("launch_id")
    if not isinstance(launch_id, str) or not launch_id or "\x00" in launch_id:
        raise RuntimeError("worker health missing or malformed launch_id")

    members: list[tuple[str, Path, str | None]] = []

    for key in ("script", "profile", "settings"):
        raw_path = health.get(key)
        claimed_digest = health.get(f"{key}_digest")

        if (
            not isinstance(raw_path, str)
            or not raw_path
            or "\x00" in raw_path
        ):
            raise RuntimeError(f"worker health missing or malformed {key} pathname")

        path = Path(raw_path)
        if not path.is_absolute():
            raise RuntimeError(f"worker health {key} pathname is not absolute: {path}")

        if claimed_digest is not None and (
            not isinstance(claimed_digest, str) or not claimed_digest
        ):
            raise RuntimeError(f"worker health malformed {key} digest")

        try:
            st = path.lstat()
        except FileNotFoundError:
            if key == "settings" and claimed_digest is None:
                members.append((key, path, None))
                continue

            raise RuntimeError(
                f"worker health required file is missing: {path}"
            ) from None
        except OSError as exc:
            raise RuntimeError(
                f"worker health cannot inspect {key}: {path}: {exc}"
            ) from exc

        if not stat.S_ISREG(st.st_mode):
            raise RuntimeError(
                f"worker health {key} is not a regular file: {path}"
            )

        actual_digest = digest(path)
        if actual_digest is None:
            raise RuntimeError(
                f"worker health cannot read stable {key} contents: {path}"
            )

        if claimed_digest is None:
            raise RuntimeError(
                f"worker health missing digest for existing {key}: {path}"
            )

        if actual_digest != claimed_digest:
            raise RuntimeError(
                f"worker health {key} changed before supervisor snapshot: {path}"
            )

        members.append((key, path, actual_digest))

    return members


def publish_known_good(health: dict[str, Any]) -> None:
    ensure_private_dir(STATE)
    members = _health_members(health)
    tmp = Path(tempfile.mkdtemp(prefix="known_good.", dir=str(STATE)))
    os.chmod(tmp, 0o700)
    try:
        files: list[dict[str, str]] = []
        for key, src, expected in members:
            if expected is None:
                files.append(
                    {"kind": key, "installed": str(src), "saved": "", "digest": "", "present": False}
                )
                continue
            name = f"{key}{src.suffix or '.dat'}"
            dst = tmp / name
            copy_durable(src, dst)
            saved_digest = digest(dst)
            if saved_digest != expected:
                raise RuntimeError(f"known-good snapshot verification failed for {key}")
            files.append(
                {"kind": key, "installed": str(src), "saved": name, "digest": expected, "present": True}
            )
        payload = {
            "schema": 2,
            "published": time.time(),
            "launch_id": health.get("launch_id", ""),
            "work_tree": str(health.get("work_tree", "")),
            "git_dir": str(health.get("git_dir", "")),
            "files": files,
        }
        atomic_json_write(tmp / "manifest.json", payload)
        fsync_dir(tmp)

        # Two-generation atomic publication. A crash at every rename boundary is
        # recoverable by recover_supervisor_state().
        if PREVIOUS.exists():
            _remove_tree(PREVIOUS)
        if KNOWN.exists():
            os.replace(KNOWN, PREVIOUS)
            fsync_dir(STATE)
        os.replace(tmp, KNOWN)
        fsync_dir(STATE)
        if not bundle_valid(KNOWN):
            raise RuntimeError("published known-good bundle failed self-verification")
        if PREVIOUS.exists():
            _remove_tree(PREVIOUS)
    except BaseException:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        # Restore the previous durable generation immediately whenever the new
        # publication is absent or fails verification. Startup recovery performs
        # the same operation after a process/power interruption.
        if not bundle_valid(KNOWN) and bundle_valid(PREVIOUS):
            if KNOWN.exists():
                failed = STATE / f"known_good.failed.{time.time_ns()}"
                os.replace(KNOWN, failed)
                fsync_dir(STATE)
            os.replace(PREVIOUS, KNOWN)
            fsync_dir(STATE)
        raise


def installed_signature(manifest: dict[str, Any] | None = None) -> list[dict[str, str]]:
    manifest = manifest or read_manifest(KNOWN)
    if not manifest:
        return []
    result: list[dict[str, str]] = []
    for rec in manifest["files"]:
        installed = Path(rec["installed"])
        result.append(
            {
                "kind": str(rec["kind"]),
                "installed": str(installed),
                "digest": digest(installed) or "",
            }
        )
    return result


def remember_rejected_candidate() -> None:
    files = installed_signature()
    if not files:
        return
    atomic_json_write(
        REJECTED,
        {
            "schema": 1,
            "rejected_epoch": time.time(),
            "expires_epoch": time.time() + REJECTED_TTL_SEC,
            "files": files,
        },
    )


def _fsync_path(path: Path) -> bool:
    try:
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            fsync_dir(path.parent)
            return True
        if stat.S_ISREG(st.st_mode):
            fd = os.open(str(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            fsync_dir(path.parent)
            return True
        if stat.S_ISDIR(st.st_mode):
            for root, dirs, files in os.walk(path, topdown=False, followlinks=False):
                root_p = Path(root)
                for name in files:
                    fp = root_p / name
                    fst = fp.lstat()
                    if stat.S_ISREG(fst.st_mode):
                        fd = os.open(str(fp), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                for name in dirs:
                    dp = root_p / name
                    if not stat.S_ISLNK(dp.lstat().st_mode):
                        fsync_dir(dp)
                fsync_dir(root_p)
            fsync_dir(path.parent)
            return True
    except OSError:
        return False
    return False


def _preserve_conflict(path: Path, index: int) -> Path:
    conflict_root = STATE / "rollback_conflicts" / str(time.time_ns())
    ensure_private_dir(conflict_root)
    conflict = conflict_root / f"{index}_{path.name}"
    try:
        os.replace(path, conflict)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        shutil.move(str(path), str(conflict))
    if not _fsync_path(conflict):
        raise RuntimeError(f"could not make rejected candidate recovery durable: {conflict}")
    fsync_dir(path.parent)
    fsync_dir(conflict_root)
    return conflict


def restore_known_good() -> bool:
    data = read_manifest(KNOWN)
    if not data:
        return False
    staged: list[tuple[Path, Path, str]] = []
    try:
        ensure_private_dir(STATE)
        atomic_json_write(
            ROLLBACK_JOURNAL,
            {"schema": 1, "started_epoch": time.time(), "next_index": 0, "count": len(data["files"])},
        )
        missing_targets: list[Path] = []
        for rec in data["files"]:
            dst = Path(rec["installed"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not rec.get("present", True):
                missing_targets.append(dst)
                continue
            src = KNOWN / rec["saved"]
            if digest(src) != rec["digest"]:
                raise RuntimeError(f"known-good payload failed verification: {src}")
            fd, temp_name = tempfile.mkstemp(prefix=f".{dst.name}.recover.", dir=str(dst.parent))
            os.close(fd)
            tmp = Path(temp_name)
            copy_durable(src, tmp)
            if digest(tmp) != rec["digest"]:
                raise RuntimeError(f"staged rollback payload failed verification: {dst}")
            staged.append((tmp, dst, rec["digest"]))

        total_ops = len(staged) + len(missing_targets)
        for index, (tmp, dst, expected) in enumerate(staged):
            try:
                st = dst.lstat()
            except FileNotFoundError:
                st = None
            if st is not None:
                current = digest(dst)
                # Preserve every displaced non-known-good object, including a
                # locally edited regular file, symlink, or unexpected directory.
                if current != expected or not stat.S_ISREG(st.st_mode):
                    _preserve_conflict(dst, index)
            os.replace(tmp, dst)
            fsync_dir(dst.parent)
            if digest(dst) != expected:
                raise RuntimeError(f"rollback verification failed: {dst}")
            atomic_json_write(
                ROLLBACK_JOURNAL,
                {"schema": 1, "started_epoch": time.time(), "next_index": index + 1, "count": total_ops},
            )

        for offset, dst in enumerate(missing_targets, start=len(staged)):
            try:
                st = dst.lstat()
            except FileNotFoundError:
                st = None
            if st is not None:
                _preserve_conflict(dst, offset)
            atomic_json_write(
                ROLLBACK_JOURNAL,
                {"schema": 1, "started_epoch": time.time(), "next_index": offset + 1, "count": total_ops},
            )

        ROLLBACK_JOURNAL.unlink(missing_ok=True)
        fsync_dir(STATE)
        return installed_matches_known()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        for tmp, _, _ in staged:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def installed_matches_known() -> bool:
    data = read_manifest(KNOWN)
    if not data:
        return False
    for rec in data["files"]:
        actual = digest(Path(rec["installed"]))
        if rec.get("present", True):
            if actual != rec["digest"]:
                return False
        else:
            try:
                Path(rec["installed"]).lstat()
            except FileNotFoundError:
                pass
            except OSError:
                return False
            else:
                return False
    return True


def _clear_control() -> None:
    ensure_private_dir(CONTROL)
    for p in CONTROL.glob("ack_*"):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        (CONTROL / "health.json").unlink()
    except OSError:
        pass
    fsync_dir(CONTROL)


def run_once(argv: list[str]) -> tuple[int, int]:
    _clear_control()
    env = os.environ.copy()
    env["DUSKY_SUPERVISOR_CONTROL_DIR"] = str(CONTROL)
    env["DUSKY_SUPERVISOR_STATE_DIR"] = str(STATE)
    proc = subprocess.Popen([sys.executable, str(SCRIPT), *argv], env=env)
    last_launch = ""
    healthy_count = 0
    try:
        while proc.poll() is None:
            health = read_json(CONTROL / "health.json")
            if isinstance(health, dict):
                launch_id = health.get("launch_id")
                if isinstance(launch_id, str) and launch_id and launch_id != last_launch:
                    try:
                        publish_known_good(health)
                        ack = CONTROL / f"ack_{launch_id}"
                        fd = os.open(
                            str(ack),
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                            0o600,
                        )
                        os.close(fd)
                        fsync_dir(CONTROL)
                    except Exception as e:
                        print(f"[FATAL] cannot publish durable known-good bundle: {e}", file=sys.stderr)
                        with suppress(OSError, ProcessLookupError):
                            proc.send_signal(signal.SIGTERM)
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                        return 70, healthy_count
                    last_launch = launch_id
                    healthy_count += 1
            time.sleep(0.05)
        return proc.wait(), healthy_count
    except KeyboardInterrupt:
        try:
            proc.send_signal(signal.SIGINT)
            return proc.wait(timeout=10), healthy_count
        except Exception:
            proc.kill()
            proc.wait()
            return 130, healthy_count


def _run_supervised() -> int:
    # A preview must remain filesystem-read-only, including supervisor state.
    if "--dry-run" in sys.argv[1:]:
        if not SCRIPT.is_file():
            print(f"[FATAL] updater not found: {SCRIPT}", file=sys.stderr)
            return 1
        return subprocess.run([sys.executable, str(SCRIPT), *sys.argv[1:]], check=False).returncode

    try:
        recover_supervisor_state()
    except Exception as e:
        print(f"[FATAL] supervisor recovery failed: {e}", file=sys.stderr)
        return 70

    # A between-run bundle mismatch can be either an interrupted activation or
    # an intentional local edit. Do not overwrite a runnable edited bundle just
    # because it differs from the previous generation: launch it as a candidate
    # and require it to reach the startup-health checkpoint. If it fails before
    # health, the post-run rollback below restores known-good while preserving
    # the displaced candidate in rollback_conflicts.
    #
    # A missing/non-regular updater cannot be launched to prove itself, so that
    # specific case must restore known-good before process creation.
    if digest(SCRIPT) is None:
        if bundle_valid(KNOWN):
            print(
                "[WARN] updater is missing or non-regular; restoring known-good generation before launch",
                file=sys.stderr,
            )
            try:
                remember_rejected_candidate()
            except Exception as e:
                print(f"[WARN] could not record rejected candidate identity: {e}", file=sys.stderr)
            if not restore_known_good():
                print(
                    f"[FATAL] startup rollback failed; recovery bundle retained at {KNOWN}",
                    file=sys.stderr,
                )
                return 70
        else:
            print(f"[FATAL] updater not found and no recoverable known-good script exists: {SCRIPT}", file=sys.stderr)
            return 1

    if digest(SCRIPT) is None:
        print(f"[FATAL] updater is still unavailable after recovery: {SCRIPT}", file=sys.stderr)
        return 1

    rc, _healthy = run_once(sys.argv[1:])

    # Roll back only when the installed bundle differs from the last durable
    # startup-health acknowledgement. Ordinary child-task failure after a health
    # checkpoint does not trigger updater rollback.
    if bundle_valid(KNOWN) and not installed_matches_known():
        print(
            "[WARN] candidate did not reach a durable startup-health checkpoint; "
            "restoring the previous known-good bundle",
            file=sys.stderr,
        )
        try:
            remember_rejected_candidate()
        except Exception as e:
            print(f"[WARN] could not record rejected candidate identity: {e}", file=sys.stderr)
        if not restore_known_good():
            print(
                f"[FATAL] automatic rollback failed; recovery bundle retained at {KNOWN}",
                file=sys.stderr,
            )
            return rc if rc != 0 else 70
        # Do not immediately relaunch: doing so can fetch/select the exact same
        # rejected candidate and create a rollback loop. A later normal launch
        # can accept a different candidate; the worker blocks the recorded bad
        # bundle for a bounded seven-day rejection window.
        print(
            "[WARN] known-good bundle restored; rejected candidate will not be relaunched automatically",
            file=sys.stderr,
        )
        return rc if rc != 0 else 75
    return rc


def main() -> int:
    # Informational commands must not publish or restore an unrelated bundle.
    # The worker remains responsible for full argument validation.
    passthrough = {"--dry-run", "--help", "-h", "--version", "--doctor", "--list", "--list-once", "--forget-once"}
    if any(arg in passthrough for arg in sys.argv[1:]):
        env = os.environ.copy()
        env.pop("DUSKY_SUPERVISOR_CONTROL_DIR", None)
        env.pop("DUSKY_SUPERVISOR_STATE_DIR", None)
        return subprocess.run([sys.executable, str(SCRIPT), *sys.argv[1:]], env=env, check=False).returncode

    # The worker's runtime lock is acquired too late to protect supervisor
    # recovery/control files. Serialize the complete launch/publication/rollback
    # lifecycle, including the interval after the worker exits.
    ensure_private_dir(STATE)
    fd = os.open(str(STATE / "supervisor.lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[WARN] another Dusky supervisor is already running", file=sys.stderr)
            return 1
        return _run_supervised()
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
