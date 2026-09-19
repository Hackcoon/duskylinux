#!/usr/bin/env python3
#d: Configure OOM protection for the system (Arch Linux / Kernel 7.2+ / systemd 261+)

from __future__ import annotations

import argparse
import filecmp
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

SELF_PATH: Final[Path] = Path(__file__).resolve()

IS_DRY_RUN: Final[bool] = "-n" in sys.argv or "--dry-run" in sys.argv

def _bootstrap_rich() -> None:
    try:
        import rich  # noqa: F401
        return
    except ImportError:
        pass
    if IS_DRY_RUN:
        return
    if not shutil.which("pacman"):
        print("python-rich not found and pacman is missing. Please install python-rich manually.", file=sys.stderr)
        sys.exit(1)
    is_root = os.geteuid() == 0
    cmd = ["pacman", "-S", "--needed", "--noconfirm", "python-rich"] if is_root else ["sudo", "pacman", "-S", "--needed", "--noconfirm", "python-rich"]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("Failed to install python-rich. Please install manually.", file=sys.stderr)
        sys.exit(1)
    os.execv(sys.executable, [sys.executable, str(SELF_PATH), *sys.argv[1:]])

_bootstrap_rich()

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich import box
    HAVE_RICH = True
    console: Final[Console] = Console()
except ImportError:
    HAVE_RICH = False
    console = None  # type: ignore

def get_ram_tier() -> str:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    gib = kb / 1024 / 1024
                    if gib < 7.0:
                        return "S"
                    elif gib < 14.0:
                        return "M"
                    elif gib < 28.0:
                        return "L"
                    else:
                        return "P"
    except Exception:
        pass
    return "M"

TIER_PROFILES: Final[dict[str, dict[str, str]]] = {
    "S": {
        "pressure_above": "30%", "pressure_lasting": "3s",
        "swap_max": "85%", "swap_pressure": "10%", "swap_lasting": "2s",
        "bg_pressure_above": "20%", "bg_pressure_lasting": "2s",
    },
    "M": {
        "pressure_above": "35%", "pressure_lasting": "5s",
        "swap_max": "85%", "swap_pressure": "10%", "swap_lasting": "2s",
        "bg_pressure_above": "20%", "bg_pressure_lasting": "3s",
    },
    "L": {
        "pressure_above": "40%", "pressure_lasting": "5s",
        "swap_max": "90%", "swap_pressure": "15%", "swap_lasting": "3s",
        "bg_pressure_above": "25%", "bg_pressure_lasting": "3s",
    },
    "P": {
        "pressure_above": "40%", "pressure_lasting": "10s",
        "swap_max": "90%", "swap_pressure": "20%", "swap_lasting": "5s",
        "bg_pressure_above": "25%", "bg_pressure_lasting": "5s",
    },
}

OOMD_TUNE: Final[str] = """[OOM]
PrekillHookTimeoutSec=0s
"""

APP_SLICE: Final[str] = """[Slice]
ManagedOOMMemoryPressure=auto
ManagedOOMSwap=auto
ManagedOOMPreference=none
MemoryAccounting=yes
OOMRules=
OOMRules=30-dusky-pressure 30-dusky-swap
"""

BACKGROUND_SLICE: Final[str] = """[Slice]
ManagedOOMMemoryPressure=auto
ManagedOOMSwap=auto
ManagedOOMPreference=none
MemoryAccounting=yes
OOMRules=
OOMRules=30-dusky-background 30-dusky-swap
"""

SESSION_SLICE: Final[str] = """[Slice]
ManagedOOMPreference=avoid
MemoryAccounting=yes
"""

COMPOSITOR_SCOPE: Final[str] = """[Scope]
OOMPolicy=continue
ManagedOOMPreference=avoid
MemoryAccounting=yes
"""

USER_MANAGER_SCORE: Final[str] = """[Service]
OOMScoreAdjust=-100
OOMPolicy=continue
"""

USER_CONF: Final[str] = """[Manager]
DefaultOOMScoreAdjust=100
DefaultMemoryPressureWatch=yes
"""

OOM_SHIELD: Final[str] = """[Service]
Slice=session.slice
OOMScoreAdjust=-100
OOMPolicy=continue
ManagedOOMPreference=avoid
MemoryAccounting=yes
"""

OOMD_SERVICE_SHIELD: Final[str] = """[Service]
OOMScoreAdjust=-1000
"""

CRITICAL_USER: Final[tuple[str, ...]] = (
    "pipewire.service", "wireplumber.service", "pipewire-pulse.service",
    "xdg-desktop-portal.service", "xdg-desktop-portal-hyprland.service",
    "xdg-desktop-portal-gtk.service", "dbus.service", "mako.service",
)

DUSKY_RUN_WRAPPER: Final[str] = """#!/bin/bash
set -euo pipefail
if [[ $# -eq 0 ]]; then
  echo "usage: dusky-run [--background] <cmd> [args...]" >&2; exit 1
fi
slice="app.slice"
score=200
if [[ "$1" == "--background" ]]; then
  slice="background.slice"
  score=300
  shift
fi
if [[ $# -eq 0 ]]; then
  echo "usage: dusky-run [--background] <cmd> [args...]" >&2; exit 1
fi
if ! printf '%d\\n' "$score" > /proc/self/oom_score_adj 2>/dev/null; then
  echo "dusky-run: warning: cannot set oom_score_adj" >&2
fi
app_name="$(basename "${1}")"
exec systemd-run --user --scope --slice="$slice" --unit="app-${app_name}-${RANDOM}" --collect \\
  --property=OOMPolicy=continue \\
  --property=ManagedOOMPreference=none \\
  --property=MemoryAccounting=yes \\
  -- "$@"
"""

@dataclass(frozen=True, slots=True, kw_only=True)
class FileSpec:
    dest: Path
    content: str
    mode: int = 0o644
    desc: str

def specs(tier: str) -> list[FileSpec]:
    prof = TIER_PROFILES[tier]

    pressure_rule = f"""[Rule]
MemoryPressureAbove={prof['pressure_above']}
LastingSec={prof['pressure_lasting']}
Action=kill-by-pgscan
"""

    swap_rule = f"""[Rule]
SwapUsageMax={prof['swap_max']}
MemoryPressureAbove={prof['swap_pressure']}
LastingSec={prof['swap_lasting']}
Action=kill-by-swap
"""

    bg_pressure_rule = f"""[Rule]
MemoryPressureAbove={prof['bg_pressure_above']}
LastingSec={prof['bg_pressure_lasting']}
Action=kill-by-pgscan
"""

    s: list[FileSpec] = [
        FileSpec(dest=Path("/etc/systemd/oomd/rules.d/30-dusky-pressure.oomrule"), content=pressure_rule, desc=f"Pressure rule (app pgscan @ {prof['pressure_above']} {prof['pressure_lasting']})"),
        FileSpec(dest=Path("/etc/systemd/oomd/rules.d/30-dusky-swap.oomrule"), content=swap_rule, desc=f"Swap rule (swap @ {prof['swap_max']} + {prof['swap_pressure']} {prof['swap_lasting']})"),
        FileSpec(dest=Path("/etc/systemd/oomd/rules.d/30-dusky-background.oomrule"), content=bg_pressure_rule, desc=f"Background pressure rule (bg pgscan @ {prof['bg_pressure_above']} {prof['bg_pressure_lasting']})"),
        FileSpec(dest=Path("/etc/systemd/oomd.conf.d/10-desktop-tune.conf"), content=OOMD_TUNE, desc="oomd global tuning (0s prekill hook)"),
        FileSpec(dest=Path("/etc/systemd/user/app.slice.d/90-desktop-oomd.conf"), content=APP_SLICE, desc="app.slice rules (30-dusky-pressure, 30-dusky-swap)"),
        FileSpec(dest=Path("/etc/systemd/user/background.slice.d/90-desktop-oomd.conf"), content=BACKGROUND_SLICE, desc="background.slice rules (30-dusky-background, 30-dusky-swap)"),
        FileSpec(dest=Path("/etc/systemd/user/session.slice.d/90-desktop-oomd.conf"), content=SESSION_SLICE, desc="session.slice protection (avoid)"),
        FileSpec(dest=Path("/etc/systemd/system/session-.scope.d/90-desktop-oomd.conf"), content=COMPOSITOR_SCOPE, desc="session-*.scope compositor protect (continue, avoid)"),
        FileSpec(dest=Path("/etc/systemd/system/user@.service.d/90-desktop-oom-score.conf"), content=USER_MANAGER_SCORE, desc="user@ service score (-100, continue)"),
        FileSpec(dest=Path("/etc/systemd/user.conf.d/90-desktop-oom.conf"), content=USER_CONF, desc="user manager default score (100, pressure watch)"),
        FileSpec(dest=Path("/etc/systemd/system/systemd-oomd.service.d/90-desktop-oomd.conf"), content=OOMD_SERVICE_SHIELD, desc="systemd-oomd daemon shield (-1000)"),
        FileSpec(dest=Path("/usr/local/bin/dusky-run"), content=DUSKY_RUN_WRAPPER, mode=0o755, desc="dusky-run wrapper"),
    ]
    for svc in CRITICAL_USER:
        s.append(FileSpec(dest=Path(f"/etc/systemd/user/{svc}.d/90-desktop-oom.conf"), content=OOM_SHIELD, desc=f"Shield {svc}"))
    return s

def atomic_install(spec: FileSpec) -> str:
    d = spec.dest
    d.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(dir=str(d.parent), prefix=f".{d.name}.tmp.")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(spec.content)
            if not spec.content.endswith("\n"):
                f.write("\n")
        os.chmod(tmp_path_str, spec.mode)
        content_equal = d.exists() and filecmp.cmp(tmp_path_str, str(d), shallow=False)
        mode_equal = d.exists() and (d.stat().st_mode & 0o777) == spec.mode
        if content_equal and mode_equal:
            return "up-to-date"
        if content_equal and not mode_equal:
            d.chmod(spec.mode)
            return "updated"
        os.replace(tmp_path_str, str(d))
        return "updated"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

def reload_user_manager() -> None:
    users: list[tuple[int, str]] = []
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            pw = pwd.getpwnam(sudo_user)
            users.append((pw.pw_uid, sudo_user))
        except KeyError:
            pass

    run_user_dir = Path("/run/user")
    if run_user_dir.is_dir():
        for p in run_user_dir.iterdir():
            if p.is_dir() and p.name.isdigit():
                uid = int(p.name)
                if uid >= 1000:
                    try:
                        uname = pwd.getpwuid(uid).pw_name
                        if (uid, uname) not in users:
                            users.append((uid, uname))
                    except KeyError:
                        pass

    if not users:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return

    for uid, username in users:
        try:
            runtime = f"/run/user/{uid}"
            if not Path(runtime).is_dir():
                continue
            env = {
                "XDG_RUNTIME_DIR": runtime,
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
            }
            subprocess.run(
                ["runuser", "-u", username, "-w", "XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS", "--",
                 "systemctl", "--user", "daemon-reload"],
                env={**os.environ, **env}, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            if HAVE_RICH and console:
                console.print(f"[yellow]User manager reload skipped for {username}: {e}[/]")
            else:
                print(f"[WARN] User manager reload skipped for {username}: {e}")

def main() -> None:
    ap = argparse.ArgumentParser(description="Deploy Hyprland/Desktop OOM config (Arch latest, systemd 261+)")
    ap.add_argument("-n", "--dry-run", action="store_true", help="Show what would change")
    ap.add_argument("--tier", choices=["S", "M", "L", "P"], default=None, help="Override detected RAM tier (S, M, L, P)")
    args = ap.parse_args()

    tier = args.tier or get_ram_tier()

    if not args.dry_run and os.geteuid() != 0:
        if HAVE_RICH and console:
            console.print("[blue]Re-executing via sudo...[/]")
        else:
            print("[INFO] Re-executing via sudo...")
        os.execvp("sudo", ["sudo", sys.executable, str(SELF_PATH), *sys.argv[1:]])

    if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        if HAVE_RICH and console:
            console.print("[red]cgroup v2 is required for systemd-oomd[/]")
        else:
            print("[ERROR] cgroup v2 is required for systemd-oomd", file=sys.stderr)
        sys.exit(1)

    all_specs = specs(tier)

    if args.dry_run:
        if HAVE_RICH and console:
            t = Table(box=box.SIMPLE_HEAVY)
            t.add_column("Action"); t.add_column("Destination"); t.add_column("Description"); t.add_column("Mode")
            for x in all_specs:
                t.add_row("install", str(x.dest), x.desc, oct(x.mode))
            console.print(Panel.fit(f"[bold cyan]DRY RUN: systemd 261+ OOM & Compositor Configuration (Tier: {tier})[/]", box=box.DOUBLE))
            console.print(t)
        else:
            print(f"--- DRY RUN PLAN (Tier: {tier}) ---")
            for x in all_specs:
                print(f"INSTALL: {x.dest} ({x.desc}) [Mode: {oct(x.mode)}]")
        return

    if HAVE_RICH and console:
        console.print(Panel.fit(f"[bold cyan]Deploying systemd 261+ OOM Configuration (Tier {tier} Optimized)[/]", box=box.DOUBLE))
    else:
        print(f"Deploying systemd 261+ OOM Configuration (Tier {tier} Optimized)")

    updated = 0
    if HAVE_RICH and console:
        with Progress(SpinnerColumn(), BarColumn(), TextColumn("{task.description}"), console=console) as prog:
            task = prog.add_task("Installing configurations", total=len(all_specs))
            results: list[tuple[FileSpec, str]] = []
            for sp in all_specs:
                st = atomic_install(sp)
                results.append((sp, st))
                if st == "updated":
                    updated += 1
                prog.advance(task)

        for sp, st in results:
            col = "green" if st == "updated" else "dim"
            console.print(f"[{col}]{st.upper():11}[/] {sp.dest} [dim]({sp.desc})[/]")
    else:
        for sp in all_specs:
            st = atomic_install(sp)
            if st == "updated":
                updated += 1
            print(f"{st.upper():11} {sp.dest} ({sp.desc})")

    subprocess.run(["systemctl", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    reload_user_manager()

    cmds = [
        ["systemctl", "enable", "--now", "systemd-oomd"],
        ["systemctl", "restart", "systemd-oomd"],
    ]
    for c in cmds:
        subprocess.run(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    oomd_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "systemd-oomd"],
        check=False
    ).returncode == 0
    status_str = "[green]active[/]" if (HAVE_RICH and oomd_active) else ("active" if oomd_active else "inactive")

    prof = TIER_PROFILES[tier]
    msg = (
        f"✔ {updated} updated, {len(all_specs)-updated} up-to-date\n"
        f"✔ systemd-oomd tier: {tier} (App: {prof['pressure_above']}/{prof['pressure_lasting']}, Swap: {prof['swap_max']}+{prof['swap_pressure']}/{prof['swap_lasting']}, Bg: {prof['bg_pressure_above']}/{prof['bg_pressure_lasting']})\n"
        f"✔ systemd-oomd status: {status_str}\n"
        f"✔ Verify with: oomctl dump && systemctl status systemd-oomd\n"
        f"✔ Note: Re-login required for DefaultOOMScoreAdjust to apply to newly spawned sessions"
    )

    if HAVE_RICH and console:
        console.print(Panel.fit(f"[bold green]{msg}[/]", box=box.ROUNDED))
    else:
        print(msg)

if __name__ == "__main__":
    main()
