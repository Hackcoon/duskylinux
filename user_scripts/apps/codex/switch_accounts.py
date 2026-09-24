#!/usr/bin/env python3
"""Switch local Codex CLI accounts stored in CODEX_HOME/auth.json.

Credentials are copied into CODEX_HOME/account-switcher with private permissions.
Close Codex before changing accounts; running processes can overwrite auth.json.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class SwitchError(Exception):
    pass


def home() -> Path:
    value = os.environ.get("CODEX_HOME")
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise SwitchError("CODEX_HOME must be an absolute path")
        return path
    return Path.home() / ".codex"


def check_name(name: str) -> str:
    if not NAME.fullmatch(name) or name in {".", ".."}:
        raise SwitchError("Name must be 1–64 letters, digits, dots, dashes, or underscores, starting with a letter or digit")
    return name


def private_dir(path: Path) -> None:
    if path.is_symlink():
        raise SwitchError(f"Refusing symbolic link: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise SwitchError(f"Not a directory: {path}")
    os.chmod(path, 0o700)


def read_regular(path: Path) -> bytes | None:
    if path.is_symlink():
        raise SwitchError(f"Refusing symbolic link: {path}")
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise SwitchError(f"Not a regular file: {path}")
    return path.read_bytes()


def atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise SwitchError(f"Refusing symbolic link: {path}")
    fd, temp = tempfile.mkstemp(prefix=".switch-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def parse_auth(data: bytes | None) -> dict:
    if not data:
        raise SwitchError("No Codex credentials found in auth.json")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError("Invalid auth.json JSON") from exc
    if not isinstance(value, dict):
        raise SwitchError("Invalid auth.json format")
    tokens = value.get("tokens")
    if isinstance(tokens, dict) and all(isinstance(tokens.get(k), str) and tokens[k] for k in ("access_token", "refresh_token")):
        return value
    if isinstance(value.get("OPENAI_API_KEY"), str) and value["OPENAI_API_KEY"]:
        return value
    raise SwitchError("auth.json contains neither usable ChatGPT tokens nor an API key")


def identity(auth: dict) -> str:
    tokens = auth.get("tokens")
    if isinstance(tokens, dict) and tokens.get("account_id"):
        return "chatgpt:" + str(tokens["account_id"])
    if auth.get("OPENAI_API_KEY"):
        return "api:" + hashlib.sha256(auth["OPENAI_API_KEY"].encode()).hexdigest()
    # Older credentials may omit account_id. Use a stable JWT claim when present.
    if isinstance(tokens, dict) and tokens.get("id_token"):
        try:
            payload = tokens["id_token"].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if isinstance(claims, dict) and isinstance(claims.get("sub"), str):
                return "sub:" + claims["sub"]
        except (IndexError, ValueError, UnicodeDecodeError, TypeError):
            pass
        return "id:" + hashlib.sha256(tokens["id_token"].encode()).hexdigest()
    raise SwitchError("Cannot identify the account in auth.json")


def profile_path(root: Path, name: str) -> Path:
    return root / "profiles" / (check_name(name) + ".json")


def active_name(root: Path) -> str | None:
    data = read_regular(root / "active")
    return check_name(data.decode().strip()) if data else None


def set_active(root: Path, name: str) -> None:
    atomic_write(root / "active", (check_name(name) + "\n").encode())


def ensure_file_store(codex_home: Path) -> None:
    """Make normal Codex launches use the same file this script switches."""
    config = codex_home / "config.toml"
    data = read_regular(config)
    if data is None:
        atomic_write(config, b'cli_auth_credentials_store = "file"\n')
        return
    try:
        parsed = tomllib.loads(data.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SwitchError("Cannot parse Codex config.toml") from exc
    store = parsed.get("cli_auth_credentials_store")
    if store == "file":
        return
    if store is not None:
        raise SwitchError(f'config.toml sets cli_auth_credentials_store = "{store}"; change it to "file" first')
    atomic_write(config, b'cli_auth_credentials_store = "file"\n' + data)


def running_codex() -> list[int]:
    """Find this user's Codex CLI processes on Linux, excluding this script."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            comm = (entry / "comm").read_text().strip().lower()
            if comm in {"codex", "codex-cli"}:
                found.append(int(entry.name))
        except (OSError, UnicodeError):
            continue
    return found


def require_closed() -> None:
    pids = running_codex()
    if pids:
        raise SwitchError(f"Close running Codex sessions first (PIDs: {', '.join(map(str, pids))})")


@contextlib.contextmanager
def locked(root: Path):
    private_dir(root)
    private_dir(root / "profiles")
    with open(root / ".lock", "a+b") as file:
        os.fchmod(file.fileno(), 0o600)
        fcntl.flock(file, fcntl.LOCK_EX)
        yield


def save_current(codex_home: Path, root: Path, name: str) -> None:
    data = read_regular(codex_home / "auth.json")
    new_auth = parse_auth(data)
    old_name = active_name(root)
    if old_name:
        old_path = profile_path(root, old_name)
        old_data = read_regular(old_path)
        if old_data and identity(parse_auth(old_data)) != identity(new_auth):
            raise SwitchError("Active auth.json belongs to a different account than the saved active name; inspect it before switching")
        atomic_write(old_path, data)
    target = profile_path(root, name)
    if name != old_name and read_regular(target) is not None:
        raise SwitchError(f"Account already exists: {name}")
    atomic_write(target, data)
    set_active(root, name)


def switch(codex_home: Path, root: Path, name: str) -> None:
    require_closed()
    target_data = read_regular(profile_path(root, name))
    parse_auth(target_data)
    old_name = active_name(root)
    if old_name == name:
        print(f"Already active: {name}")
        return
    current = read_regular(codex_home / "auth.json")
    if current:
        parse_auth(current)
        if old_name is None:
            raise SwitchError("Save the current login first: switch_accounts.py save NAME")
        saved = read_regular(profile_path(root, old_name))
        if saved is None or identity(parse_auth(saved)) != identity(parse_auth(current)):
            raise SwitchError("Active auth.json does not match the saved account; refusing to overwrite its snapshot")
        atomic_write(profile_path(root, old_name), current)
    atomic_write(codex_home / "auth.json", target_data)
    try:
        set_active(root, name)
    except Exception:
        if current is not None:
            atomic_write(codex_home / "auth.json", current)
        else:
            (codex_home / "auth.json").unlink(missing_ok=True)
        raise
    print(f"Switched to {name}. Start a new Codex session to use it.")


def login(codex_home: Path, root: Path, name: str, device_auth: bool) -> None:
    require_closed()
    check_name(name)
    if read_regular(profile_path(root, name)) is not None:
        raise SwitchError(f"Account already exists: {name}")
    old_name = active_name(root)
    previous = read_regular(codex_home / "auth.json")
    if previous:
        parse_auth(previous)
        if not old_name:
            raise SwitchError("Save the current login first: switch_accounts.py save NAME")
        saved = read_regular(profile_path(root, old_name))
        if saved is None or identity(parse_auth(saved)) != identity(parse_auth(previous)):
            raise SwitchError("Active auth.json does not match the saved account")
        atomic_write(profile_path(root, old_name), previous)
    codex = shutil.which("codex")
    if not codex:
        raise SwitchError("Codex CLI executable not found in PATH")
    (codex_home / "auth.json").unlink(missing_ok=True)
    command = [codex, "login", "-c", 'cli_auth_credentials_store="file"']
    if device_auth:
        command.append("--device-auth")
    try:
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise SwitchError(f"Codex login exited with status {result.returncode}")
        new_data = read_regular(codex_home / "auth.json")
        parse_auth(new_data)
        atomic_write(codex_home / "auth.json", new_data)
        atomic_write(profile_path(root, name), new_data)
        set_active(root, name)
    except BaseException:
        if previous is not None:
            atomic_write(codex_home / "auth.json", previous)
        else:
            (codex_home / "auth.json").unlink(missing_ok=True)
        raise
    print(f"Signed in and saved {name}.")


def import_file(root: Path, source: Path, name: str) -> None:
    data = read_regular(source)
    parse_auth(data)
    target = profile_path(root, name)
    if read_regular(target) is not None:
        raise SwitchError(f"Account already exists: {name}")
    atomic_write(target, data)
    print(f"Imported {name}. Use 'switch {name}' to activate it.")


def show(root: Path) -> None:
    current = active_name(root)
    names = sorted(p.stem for p in (root / "profiles").glob("*.json") if p.is_file() and not p.is_symlink())
    if not names:
        print("No saved accounts. Run 'save NAME' for your current login.")
    for name in names:
        print(("* " if name == current else "  ") + name)


def menu(codex_home: Path, root: Path) -> None:
    while True:
        print("\nCodex accounts (* = active)")
        show(root)
        print("\n1 Save current  2 Switch  3 Login another  4 Import auth.json  5 Quit")
        choice = input("> ").strip()
        if choice == "5" or not choice:
            return
        try:
            if choice == "1":
                require_closed()
                ensure_file_store(codex_home)
                save_current(codex_home, root, input("Account name: ").strip())
            elif choice == "2":
                ensure_file_store(codex_home)
                switch(codex_home, root, input("Account name: ").strip())
            elif choice == "3":
                ensure_file_store(codex_home)
                login(codex_home, root, input("New account name: ").strip(), False)
            elif choice == "4":
                import_file(root, Path(input("Path to auth.json: ").strip()).expanduser(), input("Account name: ").strip())
            else:
                print("Choose 1–5.")
        except (SwitchError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="Show saved accounts")
    sub.add_parser("current", help="Show active account name")
    for action in ("save", "switch", "login"):
        command = sub.add_parser(action)
        command.add_argument("name")
        if action == "login":
            command.add_argument("--device-auth", action="store_true")
    imported = sub.add_parser("import", help="Save credentials from another auth.json")
    imported.add_argument("name")
    imported.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    codex_home = home()
    root = codex_home / "account-switcher"
    try:
        private_dir(codex_home)
        with locked(root):
            if args.command == "list":
                show(root)
            elif args.command == "current":
                print(active_name(root) or "No active account saved")
            elif args.command == "import":
                import_file(root, args.path.expanduser(), args.name)
            elif args.command == "save":
                require_closed()
                ensure_file_store(codex_home)
                save_current(codex_home, root, args.name)
                print(f"Saved current login as {args.name}.")
            elif args.command == "switch":
                ensure_file_store(codex_home)
                switch(codex_home, root, args.name)
            elif args.command == "login":
                ensure_file_store(codex_home)
                login(codex_home, root, args.name, args.device_auth)
            else:
                menu(codex_home, root)
        return 0
    except (SwitchError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
