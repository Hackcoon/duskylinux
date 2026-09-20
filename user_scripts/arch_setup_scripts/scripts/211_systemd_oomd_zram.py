#!/usr/bin/env python3
#d: Configure OOM protection for the system (Arch Linux / Kernel 7.2+ / systemd 261+)

from __future__ import annotations

import argparse
import filecmp
import os
import pwd
import shlex
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
        "swap_max": "80%", "swap_pressure": "5%", "swap_lasting": "1s",
        "bg_pressure_above": "20%", "bg_pressure_lasting": "2s",
    },
    "M": {
        "pressure_above": "35%", "pressure_lasting": "5s",
        "swap_max": "80%", "swap_pressure": "5%", "swap_lasting": "1s",
        "bg_pressure_above": "20%", "bg_pressure_lasting": "3s",
    },
    "L": {
        "pressure_above": "40%", "pressure_lasting": "5s",
        "swap_max": "80%", "swap_pressure": "10%", "swap_lasting": "2s",
        "bg_pressure_above": "25%", "bg_pressure_lasting": "3s",
    },
    "P": {
        "pressure_above": "40%", "pressure_lasting": "10s",
        "swap_max": "80%", "swap_pressure": "15%", "swap_lasting": "3s",
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
preference="avoid"
grace_sec="${DUSKY_GRACE_SEC:-8}"

if [[ "$1" == "--background" ]]; then
  slice="background.slice"
  score=300
  preference="none"
  shift
fi

if [[ $# -eq 0 ]]; then
  echo "usage: dusky-run [--background] <cmd> [args...]" >&2; exit 1
fi

if ! printf '%d\\n' "$score" > /proc/self/oom_score_adj 2>/dev/null; then
  echo "dusky-run: warning: cannot set oom_score_adj" >&2
fi

app_name="$(basename "${1}")"
unit="app-${app_name}-${RANDOM}"

# Grace period: Protect newly launched interactive apps with ManagedOOMPreference=avoid
# for the first grace_sec (default 8s), then revert to ManagedOOMPreference=none.
if [[ "$preference" == "avoid" ]]; then
  (
    sleep "$grace_sec"
    systemctl --user set-property "${unit}.scope" ManagedOOMPreference=none 2>/dev/null || true
  ) &
fi

exec systemd-run --user --scope --slice="$slice" --unit="$unit" --collect \\
  --property=OOMPolicy=continue \\
  --property=ManagedOOMPreference="$preference" \\
  --property=MemoryAccounting=yes \\
  -- "$@"
"""

DUSKY_OOM_SHIELD_C: Final[str] = """#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <unistd.h>
#include <poll.h>
#include <dirent.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/xattr.h>
#include <sys/stat.h>
#include <sys/time.h>

#define MAX_PROTECTED 128
#define PATH_MAX_LEN 512

static char protected_cgroups[MAX_PROTECTED][PATH_MAX_LEN];
static int num_protected = 0;
static volatile sig_atomic_t g_running = 1;

static void handle_sig(int sig) {
    (void)sig;
    g_running = 0;
}

static const char *find_matching_brace(const char *start) {
    int depth = 0;
    bool in_str = false;
    bool esc = false;
    for (const char *p = start; *p; p++) {
        if (esc) { esc = false; continue; }
        if (*p == '\\\\') { esc = true; continue; }
        if (*p == '"') { in_str = !in_str; continue; }
        if (!in_str) {
            if (*p == '{') depth++;
            else if (*p == '}') {
                depth--;
                if (depth == 0) return p;
            }
        }
    }
    return NULL;
}

static int parse_active_pid(const char *json) {
    const char *p = strstr(json, "\\"pid\\":");
    if (!p) return -1;
    p += 6;
    while (*p == ' ' || *p == '\\t') p++;
    int pid = atoi(p);
    return (pid > 0) ? pid : -1;
}

static int parse_pinned_pids(const char *json, int *pids, int max_pids) {
    int count = 0;
    const char *cur = json;
    while ((cur = strchr(cur, '{')) != NULL && count < max_pids) {
        const char *end = find_matching_brace(cur);
        if (!end) break;
        
        size_t len = (size_t)(end - cur + 1);
        if (len < 2048) {
            char block[2048];
            memcpy(block, cur, len);
            block[len] = '\\0';
            
            bool is_pinned = (strstr(block, "\\"pinned\\": true") != NULL) ||
                             (strstr(block, "\\"pinned\\":true") != NULL);
            if (is_pinned) {
                const char *pp = strstr(block, "\\"pid\\":");
                if (pp) {
                    pp += 6;
                    while (*pp == ' ' || *pp == '\\t') pp++;
                    int pid = atoi(pp);
                    if (pid > 0) {
                        pids[count++] = pid;
                    }
                }
            }
        }
        cur = end + 1;
    }
    return count;
}

static int find_hypr_sockets(char *out_cmd, size_t cmd_len, char *out_evt, size_t evt_len) {
    uid_t uid = getuid();
    char base_dir[128];
    snprintf(base_dir, sizeof(base_dir), "/run/user/%u/hypr", uid);
    
    const char *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    if (sig && *sig) {
        if (snprintf(out_cmd, cmd_len, "%s/%s/.socket.sock", base_dir, sig) < (int)cmd_len &&
            snprintf(out_evt, evt_len, "%s/%s/.socket2.sock", base_dir, sig) < (int)evt_len) {
            if (access(out_cmd, F_OK) == 0 && access(out_evt, F_OK) == 0) {
                return 0;
            }
        }
    }
    
    DIR *d = opendir(base_dir);
    if (!d) return -1;
    
    struct dirent *entry;
    while ((entry = readdir(d)) != NULL) {
        if (entry->d_type == DT_DIR && entry->d_name[0] != '.') {
            if (snprintf(out_cmd, cmd_len, "%s/%s/.socket.sock", base_dir, entry->d_name) < (int)cmd_len &&
                snprintf(out_evt, evt_len, "%s/%s/.socket2.sock", base_dir, entry->d_name) < (int)evt_len) {
                if (access(out_cmd, F_OK) == 0 && access(out_evt, F_OK) == 0) {
                    closedir(d);
                    return 0;
                }
            }
        }
    }
    closedir(d);
    return -1;
}

static int query_hyprland(const char *sock_path, const char *cmd, char *out_buf, size_t max_len) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    
    struct timeval tv = { .tv_sec = 1, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    size_t path_len = strlen(sock_path);
    if (path_len >= sizeof(addr.sun_path)) {
        close(fd);
        return -1;
    }
    memcpy(addr.sun_path, sock_path, path_len + 1);
    
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    
    if (write(fd, cmd, strlen(cmd)) < 0) {
        close(fd);
        return -1;
    }
    
    size_t total = 0;
    while (total + 1 < max_len) {
        ssize_t n = read(fd, out_buf + total, max_len - total - 1);
        if (n <= 0) break;
        total += (size_t)n;
    }
    out_buf[total] = '\\0';
    close(fd);
    return (int)total;
}

static int get_cgroup_path(int pid, char *out_path, size_t out_len) {
    char proc_path[64];
    snprintf(proc_path, sizeof(proc_path), "/proc/%d/cgroup", pid);
    FILE *f = fopen(proc_path, "r");
    if (!f) return -1;
    
    char line[512];
    int found = -1;
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "0::/", 4) == 0) {
            char *rel = line + 4;
            rel[strcspn(rel, "\\r\\n")] = '\\0';
            if (strstr(rel, "app.slice") != NULL) {
                if (snprintf(out_path, out_len, "/sys/fs/cgroup/%s", rel) < (int)out_len) {
                    struct stat st;
                    if (stat(out_path, &st) == 0 && S_ISDIR(st.st_mode)) {
                        found = 0;
                        break;
                    }
                }
            }
        }
    }
    fclose(f);
    return found;
}

static void safe_copy(char *dst, const char *src, size_t max_len) {
    if (max_len == 0) return;
    size_t len = strlen(src);
    if (len >= max_len) len = max_len - 1;
    memcpy(dst, src, len);
    dst[len] = '\\0';
}

static void sync_protection(const char *cmd_sock) {
    static char act_buf[4096];
    static char clients_buf[65536];
    
    int act_len = query_hyprland(cmd_sock, "j/activewindow", act_buf, sizeof(act_buf));
    int clients_len = query_hyprland(cmd_sock, "j/clients", clients_buf, sizeof(clients_buf));
    
    int target_pids[MAX_PROTECTED];
    int num_targets = 0;
    
    if (act_len > 0) {
        int act_pid = parse_active_pid(act_buf);
        if (act_pid > 0 && num_targets < MAX_PROTECTED) {
            target_pids[num_targets++] = act_pid;
        }
    }
    
    if (clients_len > 0) {
        int pinned_pids[MAX_PROTECTED];
        int num_pinned = parse_pinned_pids(clients_buf, pinned_pids, MAX_PROTECTED);
        for (int i = 0; i < num_pinned && num_targets < MAX_PROTECTED; i++) {
            bool already = false;
            for (int j = 0; j < num_targets; j++) {
                if (target_pids[j] == pinned_pids[i]) { already = true; break; }
            }
            if (!already) {
                target_pids[num_targets++] = pinned_pids[i];
            }
        }
    }
    
    char new_cgroups[MAX_PROTECTED][PATH_MAX_LEN];
    int num_new = 0;
    
    for (int i = 0; i < num_targets; i++) {
        char cg[PATH_MAX_LEN];
        if (get_cgroup_path(target_pids[i], cg, sizeof(cg)) == 0) {
            bool already = false;
            for (int j = 0; j < num_new; j++) {
                if (strcmp(new_cgroups[j], cg) == 0) { already = true; break; }
            }
            if (!already && num_new < MAX_PROTECTED) {
                safe_copy(new_cgroups[num_new++], cg, PATH_MAX_LEN);
            }
        }
    }
    
    // Set avoid on newly protected cgroups
    for (int i = 0; i < num_new; i++) {
        bool was_protected = false;
        for (int j = 0; j < num_protected; j++) {
            if (strcmp(new_cgroups[i], protected_cgroups[j]) == 0) {
                was_protected = true;
                break;
            }
        }
        if (!was_protected) {
            setxattr(new_cgroups[i], "user.oomd_avoid", "1", 1, 0);
        }
    }
    
    // Remove avoid from cgroups no longer active or pinned
    for (int i = 0; i < num_protected; i++) {
        bool still_protected = false;
        for (int j = 0; j < num_new; j++) {
            if (strcmp(protected_cgroups[i], new_cgroups[j]) == 0) {
                still_protected = true;
                break;
            }
        }
        if (!still_protected) {
            removexattr(protected_cgroups[i], "user.oomd_avoid");
        }
    }
    
    num_protected = num_new;
    for (int i = 0; i < num_new; i++) {
        safe_copy(protected_cgroups[i], new_cgroups[i], PATH_MAX_LEN);
    }
}

static void cleanup_all(void) {
    for (int i = 0; i < num_protected; i++) {
        removexattr(protected_cgroups[i], "user.oomd_avoid");
    }
    num_protected = 0;
}

int main(void) {
    signal(SIGTERM, handle_sig);
    signal(SIGINT, handle_sig);
    signal(SIGPIPE, SIG_IGN);
    
    char cmd_sock[PATH_MAX_LEN], evt_sock_path[PATH_MAX_LEN];
    
    while (g_running) {
        if (find_hypr_sockets(cmd_sock, sizeof(cmd_sock), evt_sock_path, sizeof(evt_sock_path)) != 0) {
            sleep(1);
            continue;
        }
        
        sync_protection(cmd_sock);
        
        int evt_fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (evt_fd < 0) {
            sleep(1);
            continue;
        }
        
        struct sockaddr_un addr;
        memset(&addr, 0, sizeof(addr));
        addr.sun_family = AF_UNIX;
        size_t path_len = strlen(evt_sock_path);
        if (path_len >= sizeof(addr.sun_path)) {
            close(evt_fd);
            sleep(1);
            continue;
        }
        memcpy(addr.sun_path, evt_sock_path, path_len + 1);
        
        if (connect(evt_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
            close(evt_fd);
            sleep(1);
            continue;
        }
        
        char buf[4096];
        size_t buf_len = 0;
        struct pollfd pfd = { .fd = evt_fd, .events = POLLIN, .revents = 0 };
        
        while (g_running) {
            int ret = poll(&pfd, 1, 2000);
            if (!g_running) break;
            
            if (ret > 0 && (pfd.revents & POLLIN)) {
                ssize_t n = read(evt_fd, buf + buf_len, sizeof(buf) - buf_len - 1);
                if (n <= 0) break;
                buf_len += (size_t)n;
                buf[buf_len] = '\\0';
                
                bool needs_sync = false;
                char *line_start = buf;
                char *nl;
                while ((nl = strchr(line_start, '\\n')) != NULL) {
                    *nl = '\\0';
                    if (strncmp(line_start, "activewindow>>", 14) == 0 ||
                        strncmp(line_start, "activewindowv2>>", 16) == 0 ||
                        strncmp(line_start, "pin>>", 5) == 0 ||
                        strncmp(line_start, "openwindow>>", 12) == 0 ||
                        strncmp(line_start, "closewindow>>", 13) == 0 ||
                        strncmp(line_start, "focusedmon>>", 12) == 0 ||
                        strncmp(line_start, "workspace>>", 11) == 0) {
                        needs_sync = true;
                    }
                    line_start = nl + 1;
                }
                
                size_t processed = (size_t)(line_start - buf);
                if (processed < buf_len) {
                    memmove(buf, line_start, buf_len - processed);
                    buf_len -= processed;
                } else {
                    buf_len = 0;
                }
                
                if (needs_sync) {
                    sync_protection(cmd_sock);
                }
            } else {
                sync_protection(cmd_sock);
            }
            
            if (pfd.revents & (POLLHUP | POLLERR | POLLNVAL)) {
                break;
            }
        }
        
        close(evt_fd);
        cleanup_all();
        if (g_running) sleep(1);
    }
    
    cleanup_all();
    return 0;
}
"""

DUSKY_OOM_SHIELD_SERVICE: Final[str] = """[Unit]
Description=Dusky OOM Shield: Dynamic Hyprland Active & Pinned Window Protection
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/local/bin/dusky-oom-shield
Restart=always
RestartSec=2s
Slice=session.slice
OOMScoreAdjust=-100
OOMPolicy=continue
ManagedOOMPreference=avoid

[Install]
WantedBy=graphical-session.target
"""

def get_makepkg_build_flags() -> tuple[list[str], list[str], str]:
    """Dynamically resolve makepkg CFLAGS/LDFLAGS without hardcoding any usernames.
    Follows makepkg sourcing hierarchy: /etc/makepkg.conf -> /etc/makepkg.conf.d/*.conf -> ~/.config/pacman/makepkg.conf.
    Ensures -march=native is present to target the host CPU architecture.
    """
    target_home: Path | None = None
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            target_home = Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass

    if not target_home:
        try:
            login_user = os.getlogin()
            if login_user and login_user != "root":
                target_home = Path(pwd.getpwnam(login_user).pw_dir)
        except Exception:
            pass

    if not target_home:
        for u in pwd.getpwall():
            if u.pw_uid >= 1000 and Path(u.pw_dir).is_dir() and not u.pw_dir.startswith("/nonexistent"):
                target_home = Path(u.pw_dir)
                break

    if not target_home:
        target_home = Path.home()

    user_makepkg: Path | None = None
    candidates = [
        target_home / ".config" / "pacman" / "makepkg.conf",
        target_home / ".makepkg.conf",
    ]
    for c in candidates:
        if c.is_file():
            user_makepkg = c
            break

    script = """
    [[ -f /etc/makepkg.conf ]] && source /etc/makepkg.conf
    for f in /etc/makepkg.conf.d/*.conf; do
        [[ -f "$f" ]] && source "$f"
    done
    if [[ -n "$USER_MAKEPKG" && -f "$USER_MAKEPKG" ]]; then
        source "$USER_MAKEPKG"
    fi
    printf "%s\\n" "${CFLAGS:-}"
    printf "%s\\n" "${LDFLAGS:-}"
    """
    env = {**os.environ, "USER_MAKEPKG": str(user_makepkg) if user_makepkg else ""}
    res = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False)
    lines = res.stdout.splitlines()
    cflags_raw = lines[0] if len(lines) > 0 else ""
    ldflags_raw = lines[1] if len(lines) > 1 else ""

    cflags = shlex.split(cflags_raw)
    ldflags = shlex.split(ldflags_raw)

    if not cflags:
        cflags = ["-march=native", "-O2", "-pipe"]
    elif not any(flag.startswith("-march=") for flag in cflags):
        cflags.insert(0, "-march=native")

    source_desc = str(user_makepkg) if user_makepkg else "/etc/makepkg.conf"
    return cflags, ldflags, source_desc

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
Action=kill-by-pgscan
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
        FileSpec(dest=Path("/usr/local/src/dusky-oom-shield.c"), content=DUSKY_OOM_SHIELD_C, mode=0o644, desc="dusky-oom-shield C source code"),
        FileSpec(dest=Path("/etc/systemd/user/dusky-oom-shield.service"), content=DUSKY_OOM_SHIELD_SERVICE, mode=0o644, desc="dusky-oom-shield user service (active/pinned window shield)"),
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
        subprocess.run(["systemctl", "--user", "enable", "--now", "dusky-oom-shield.service"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl", "--user", "restart", "dusky-oom-shield.service"], check=False,
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
            subprocess.run(
                ["runuser", "-u", username, "-w", "XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS", "--",
                 "systemctl", "--user", "enable", "--now", "dusky-oom-shield.service"],
                env={**os.environ, **env}, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(
                ["runuser", "-u", username, "-w", "XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS", "--",
                 "systemctl", "--user", "restart", "dusky-oom-shield.service"],
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
    cflags, ldflags, flag_source = get_makepkg_build_flags()

    if args.dry_run:
        if HAVE_RICH and console:
            t = Table(box=box.SIMPLE_HEAVY)
            t.add_column("Action"); t.add_column("Destination"); t.add_column("Description"); t.add_column("Mode")
            for x in all_specs:
                t.add_row("install", str(x.dest), x.desc, oct(x.mode))
            t.add_row("compile", "/usr/local/bin/dusky-oom-shield", f"Compile native C (-march=native via {flag_source})", "0o755")
            console.print(Panel.fit(f"[bold cyan]DRY RUN: systemd 261+ OOM & Compositor Configuration (Tier: {tier})[/]", box=box.DOUBLE))
            console.print(t)
        else:
            print(f"--- DRY RUN PLAN (Tier: {tier}) ---")
            for x in all_specs:
                print(f"INSTALL: {x.dest} ({x.desc}) [Mode: {oct(x.mode)}]")
            print(f"COMPILE: /usr/local/bin/dusky-oom-shield (native C, -march=native via {flag_source}) [Mode: 0o755]")
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

    # Compile native C dusky-oom-shield binary with host CPU makepkg optimization flags
    c_src = Path("/usr/local/src/dusky-oom-shield.c")
    c_bin = Path("/usr/local/bin/dusky-oom-shield")
    if c_src.exists():
        is_root = os.geteuid() == 0
        if not shutil.which("gcc"):
            cmd = ["pacman", "-S", "--needed", "--noconfirm", "gcc"] if is_root else ["sudo", "pacman", "-S", "--needed", "--noconfirm", "gcc"]
            subprocess.run(cmd, check=True)

        cflags, ldflags, flag_source = get_makepkg_build_flags()

        # If mold linker is specified in LDFLAGS, ensure mold is installed
        if any("mold" in f for f in ldflags) and not shutil.which("mold"):
            cmd = ["pacman", "-S", "--needed", "--noconfirm", "mold"] if is_root else ["sudo", "pacman", "-S", "--needed", "--noconfirm", "mold"]
            m_res = subprocess.run(cmd, check=False)
            if m_res.returncode != 0:
                ldflags = [f for f in ldflags if "mold" not in f]

        compile_cmd = ["gcc", *cflags, "-Wall", "-Wextra", "-Werror", str(c_src), "-o", str(c_bin), *ldflags]
        res = subprocess.run(compile_cmd, check=False)
        if res.returncode == 0:
            c_bin.chmod(0o755)
            if HAVE_RICH and console:
                console.print(f"[green]COMPILED   [/] /usr/local/bin/dusky-oom-shield [dim](native C binary, -march=native via {flag_source})[/]")
            else:
                print(f"COMPILED    /usr/local/bin/dusky-oom-shield (native C binary, -march=native via {flag_source})")
        else:
            if HAVE_RICH and console:
                console.print("[red]Compilation failed for dusky-oom-shield![/]")
            else:
                print("[ERROR] Compilation failed for dusky-oom-shield!", file=sys.stderr)
            sys.exit(1)

    subprocess.run(["systemctl", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    cmds = [
        ["systemctl", "enable", "--now", "systemd-oomd"],
        ["systemctl", "restart", "systemd-oomd"],
    ]
    for c in cmds:
        subprocess.run(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    reload_user_manager()

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
