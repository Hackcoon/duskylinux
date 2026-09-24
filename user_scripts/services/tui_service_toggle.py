#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

_DUSKY_TUI_ROOT = Path.home() / "user_scripts" / "dusky_tui"
if str(_DUSKY_TUI_ROOT) not in sys.path:
    sys.path.insert(0, str(_DUSKY_TUI_ROOT))

from python.frontend.core_types import ConfigItem

ENGINE_TYPE = "systemd"
TARGET_FILE = "/etc/systemd/system"
APP_TITLE = "Dusky Service Manager"
DEFAULT_MODE = "auto"
THEME_FILE = "~/.config/matugen/generated/dusky_tui.json"
ENABLE_USER_PRESETS = True
USER_PRESETS_TAB = "Presets"


TABS = [
    "Core User",
    "Core System",
    "Active",
    "Enabled",
    "Timers",
    "All User",
    "All System",
    "Presets",
]

SCHEMA = {i: [] for i in range(len(TABS))}

# --- DETAILED EXTENDED HELP DICTIONARIES ---
CORE_USER_DEFS = {
    "app-dev.lizardbyte.app.Sunshine.service": (
        "Sunshine Streaming",
        "Self-hosted game stream host for Moonlight. Streams your desktop and games to Moonlight clients. Runs as a user service and is enabled to start automatically with your graphical session (graphical-session.target). Use systemctl --user disable to stop it launching at login, or disable/enable right here.",
    ),
    "hyprsunset.service": (
        "Night Light",
        "Manages hyprsunset, a Wayland-native blue light filter. Turning this on will adjust the color temperature of your display to reduce eye strain at night.",
    ),
    "dusky_battery.service": (
        "Battery Alerts",
        "Background daemon that monitors your battery level and sends desktop notifications using libnotify when power is running low.",
    ),
    "network_meter.service": (
        "Network Traffic Meter",
        "Service to track network traffic. Often used in conjunction with Waybar to display real-time upload and download speeds.",
    ),
    "dusky.service": (
        "Dusky Background Service",
        "The primary Dusky ecosystem background service. Handles core daemon tasks required for the environment.",
    ),
    "dusky_quickpanal.service": (
        "Dusky quickpanal Service",
        "Manages the Dusky quick access panel (Quickpanal) overlay.",
    ),
    "update_checker.timer": (
        "Automatic Update Checker",
        "Periodically checks your package manager for system updates and caches the result for your status bar.",
    ),
    "hypridle.service": (
        "Hyprland Idle Daemon",
        "Hyprland's idle management daemon. Handles screen dimming, locking, and DPMS sleep states when you are away from the computer.",
    ),
    "osd_lock.service": (
        "Lock Key OSD",
        "On-Screen Display service for hardware lock keys. Shows a visual pop-up when Caps Lock, Num Lock, or Scroll Lock is toggled.",
    ),
    "dusky_polkit.service": (
        "Dusky Polkit",
        "Lightweight Python/Rich Polkit agent. Prompts for root/admin password on privilege escalation (like pkexec).",
    ),
    "dusky_clipboard.service": (
        "Dusky Clipboard Manager",
        "Unified Wayland clipboard history and persistence daemon (cliphist + wl-clip-persist). Seamlessly records copied text and images to SQLite history, preserves clipboard selections even after source apps close, and supports live RAM/disk persistence switching without reboot.",
    ),
    "dusky_ram_monitor.service": (
        "Dusky RAM Monitor",
        "Background monitor that alerts you if physical RAM usage exceeds 95% or ZRAM swap occupancy exceeds 90%. Clicking the alert opens an interactive Rofi menu to select and terminate memory-heavy processes before a system crash.",
    ),
    "dusky_visualizer.service": (
        "Audio Visualizer Daemon",
        "Background daemon for the audio visualizer. Renders visualizer shapes dynamically in the background.",
    ),
    "dusky_screentime.service": (
        "Screentime Tracker",
        "Wayland screentime tracking daemon. Connects to Hyprland UNIX socket to monitor active window durations and persist daily usage metrics.",
    ),

    "dusky_notif_time.service": (
        "Notification Timestamps",
        "Background daemon that tracks exact arrival timestamps for Mako desktop notifications and caches them for QuickPanel and Rofi displays.",
    ),
    "modprobed-db.service": (
        "Hardware Profiler",
        "Records used kernel modules to `~/.config/modprobed.db` for `localmodconfig`. Keep enabled for lean native kernels.",
    ),
    "modprobed-db.timer": (
        "Profiler Timer",
        "Triggers profiler every 6h to refresh hardware DB. Enabled via service.",
    ),
    "dusky_llm.service": (
        "LLM Service (dusky_llm)",
        "Local LLM inference daemon (Ollama / llama.cpp wrapper). Handles prompt completion and embeddings for Dusky AI features.",
    ),
    "dusky_stt.service": (
        "STT (Parakeet GPU)",
        "Speech-to-text daemon (NVIDIA Parakeet 0.6B, on-demand CUDA worker). ON = warm-resident: model preloaded, instant dictation, VRAM held (plugged-in mode). OFF = on-demand: hotkey still works, VRAM held only mid-job, then worker exits and the service stops itself so the dGPU can sleep (battery mode).",
    ),
    "dusky_firefox_cache.service": (
        "Firefox Profile RAM Sync",
        "Synchronizes Firefox profiles into RAM (tmpfs) to eliminate SSD write amplification from cookie and SQLite churn. Automatically restores to disk on shutdown, with periodic background resyncs.",
    ),
    "dusky_firefox_cache_resync.timer": (
        "Firefox RAM Cache Resync",
        "Runs the Firefox profile RAM sync every hour while the companion service is active.",
    ),
    "dusky-oom-shield.service": (
        "Dusky OOM Shield",
        "Protects the active Hyprland session and pinned windows from systemd-oomd pressure kills.",
    ),
}

CORE_SYSTEM_DEFS = {
    "vsftpd.service": (
        "FTP Server (vsftpd)",
        "Very Secure FTP Daemon. Manages the FTP server for file transfers. Only enable this if you actively need to host an FTP server.",
    ),
    "tlp.service": (
        "TLP Power Management",
        "Advanced power management for Linux. Applies various battery-saving tweaks to the kernel, PCI, and USB devices.",
    ),
    "battery-charge-limit.service": (
        "Battery Charge Limit",
        "Applies an 80% hardware battery charge limit at boot.",
    ),
    "dusky_cpu.service": (
        "CPU Power Restorer",
        "Restores your custom CPU core states and package power limit adjustments dynamically on system boot.",
    ),
    "dusky-kbd-backlight.service": (
        "Keyboard Backlight State",
        "Restores the configured keyboard backlight hardware state at boot.",
    ),
    "ghelper-gpu-boot.service": (
        "G-Helper GPU at Boot",
        "Applies the configured G-Helper GPU mode during system startup.",
    ),
    "glance_cpu_pkg_watt.service": (
        "CPU Package Power Access",
        "Allows Dusky Glance to read CPU package energy counters.",
    ),
    "numlock_disable.service": (
        "NumLock on TTY Boot",
        "Disables NumLock on virtual consoles (TTYs 1 to 6) during boot. Useful for keyboards that default to NumLock ON, preventing lock-out at the login screen.",
    ),
    "swayosd-libinput-backend.service": (
        "SwayOSD Input Backend",
        "Backend service for SwayOSD. Handles raw libinput events to render volume/brightness overlays without relying on the window manager.",
    ),
    "sshd.service": (
        "SSH Server (OpenSSH)",
        "OpenSSH server daemon. Allows remote access to this machine via SSH. Ensure your firewall is configured if exposing this to the internet.",
    ),
    "warp-svc.service": (
        "Cloudflare WARP VPN",
        "Cloudflare WARP daemon. Provides a fast, secure VPN tunnel using WireGuard to route your DNS and internet traffic.",
    ),
    "firewalld.service": (
        "Firewall (firewalld)",
        "Dynamic firewall manager. Provides a D-Bus interface to manage firewall rules and network zones.",
    ),
    "tailscaled.service": ("Tailscaled", "Allows remote access"),
    "dusky_snapshot.timer": (
        "Root + Home Snapshots",
        "Creates paired root and home snapshots daily at 8 PM and keeps up to six scheduled pairs.",
    ),
    "dusky-zram-recompress.timer": (
        "ZRAM Recompression",
        "Recompresses idle ZRAM pages every hour while the timer is enabled.",
    ),
    "dusky_boot_zram_flush.timer": (
        "ZRAM Boot Flush Timer",
        "One-shot boot memory flush timer. Triggers 60s after boot to flush cold startup memory into ZRAM swap, minimizing idle memory footprint.",
    ),
    "dusky_pro_active_zram_swap.timer": (
        "Proactive ZRAM Swap",
        "Proactive MGLRU slice skimmer timer. Checks memory every 6 minutes and reclaims cold anonymous pages into ZRAM when RAM usage reaches 70%.",
    ),
    "ufw.service": (
        "Firewall (UFW)",
        "Uncomplicated Firewall. A user-friendly front-end for iptables to manage network access rules.",
    ),
    "linux-modules-cleanup.service": (
        "Old Kernel Cleanup",
        "Oneshot boot service provided by kernel-modules-hook. Automatically cleans up orphaned kernel module directories in /usr/lib/modules after a kernel update.",
    ),
    "snapper-cleanup.timer": (
        "Snapper Cleanup Timer",
        "Runs Snapper's snapshot cleanup service every hour.",
    ),
    "fstrim.timer": (
        "Weekly SSD Trim",
        "Discards unused filesystem blocks once a week on supported storage.",
    ),
    "dusky_keylogger.service": (
        "Dusky Keystroke Stats",
        "Always-on keystroke statistics daemon. Captures raw key presses via evdev (no Wayland/X11), classifies them (Shift/Caps/NumLock, shortcut chords), and stores them with kernel timestamps in SQLite at ~/.local/share/dusky-keylogger/keys.db (mode 0600). Powers the `dusky stats` / `dusky dashboard` analytics. Stop/disable it here to pause logging.",
    ),
    "dusky_powertop_autotune.timer": (
        "Powertop Auto-Tune",
        "One-shot boot timer that runs `powertop --auto-tune` 2 minutes after boot to flip all power tunables to their Good setting. Enable this timer to auto-tune on every boot; the companion dusky_powertop_autotune.service runs only when triggered. Disabled by default because it can conflict with TLP.",
    ),
}

import concurrent.futures


# =============================================================================
# FAST TARGETED CORE FETCH (Tabs 0-1)
# Only queries the curated units instead of enumerating all installed units.
# =============================================================================
def _fetch_core_installed(scope: str, units: list[str]) -> set:
    """Checks only specific units for existence via targeted list-unit-files query."""
    if not units:
        return set()
    call = ["systemctl", "list-unit-files", "--no-pager", "--no-legend"] + units
    if scope == "user":
        call.insert(1, "--user")
    try:
        res = subprocess.run(
            call, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        installed = set()
        for line in res.stdout.splitlines():
            if not line:
                continue
            parts = line.split()
            if parts:
                installed.add(parts[0])
        return installed
    except Exception as e:
        import sys

        print(
            f"[tui_service_toggle] ERROR: _fetch_core_installed({scope}): {e}",
            file=sys.stderr,
        )
        return set()


# Fast path: query only the curated units in two subprocess calls.
_core_user_units = list(CORE_USER_DEFS.keys())
_core_sys_units = list(CORE_SYSTEM_DEFS.keys())

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _fast_exec:
    _f_core_user = _fast_exec.submit(_fetch_core_installed, "user", _core_user_units)
    _f_core_sys = _fast_exec.submit(_fetch_core_installed, "system", _core_sys_units)

    _core_installed_user = _f_core_user.result()
    _core_installed_sys = _f_core_sys.result()

# The frontend's native menu rows are value-less folders. They never reach the
# systemd engine, and their children keep their real unit keys and scopes.
CORE_USER_SECTIONS = (
    ("Desktop & Session", (
        "hyprsunset.service", "hypridle.service", "osd_lock.service",
        "dusky_polkit.service", "dusky_clipboard.service", "dusky-oom-shield.service",
    )),
    ("Panels & Integration", (
        "dusky.service", "dusky_quickpanal.service", "network_meter.service",
        "dusky_notif_time.service", "dusky_visualizer.service", "dusky_screentime.service",
    )),
    ("Media & AI", (
        "app-dev.lizardbyte.app.Sunshine.service", "dusky_llm.service", "dusky_stt.service",
    )),
    ("Power & Monitoring", (
        "dusky_battery.service", "dusky_ram_monitor.service",
    )),
    ("Storage & Maintenance", (
        "dusky_firefox_cache.service", "dusky_firefox_cache_resync.timer",
        "update_checker.timer",
    )),
    ("Kernel Compilation", (
        "modprobed-db.service", "modprobed-db.timer",
    )),
)

CORE_SYSTEM_SECTIONS = (
    ("Power & Hardware", (
        "tlp.service", "battery-charge-limit.service", "dusky_cpu.service",
        "dusky-kbd-backlight.service", "ghelper-gpu-boot.service",
        "glance_cpu_pkg_watt.service", "dusky-zram-recompress.timer",
        "dusky_boot_zram_flush.timer", "dusky_pro_active_zram_swap.timer",
        "dusky_powertop_autotune.timer",
    )),
    ("Input & Session", (
        "numlock_disable.service", "swayosd-libinput-backend.service",
        "dusky_keylogger.service",
    )),
    ("Network & Security", (
        "vsftpd.service", "sshd.service", "warp-svc.service",
        "firewalld.service", "tailscaled.service", "ufw.service",
    )),
    ("Storage & Maintenance", (
        "dusky_snapshot.timer", "linux-modules-cleanup.service",
        "snapper-cleanup.timer", "fstrim.timer",
    )),
)


def _append_core_sections(tab_idx, definitions, installed, scope, sections):
    assigned = set()
    for section_idx, (title, units) in enumerate((*sections, ("Other", tuple(definitions)))):
        members = [unit for unit in units if unit in definitions and unit in installed and unit not in assigned]
        if not members:
            continue
        folder_key = f"__core_{scope}_{section_idx}"
        SCHEMA[tab_idx].append(
            ConfigItem(
                label=f"{title} ({len(members)})",
                key=folder_key,
                type_="menu",
                default=None,
                is_parent=True,
                expanded=True,
                extended_help=f"{title}: {len(members)} installed units. Press Enter to expand or collapse.",
            )
        )
        for unit in members:
            label, help_text = definitions[unit]
            SCHEMA[tab_idx].append(
                ConfigItem(
                    label=label,
                    key=unit,
                    scope=scope,
                    type_="bool",
                    default=False,
                    parent_ref=folder_key,
                    extended_help=f"**Unit:** `{unit}`\n**Scope:** {scope.title()}\n\n{help_text}",
                )
            )
        assigned.update(members)


# --- TABS 0-1: CURATED CORE UNITS (instant) ---
_append_core_sections(0, CORE_USER_DEFS, _core_installed_user, "user", CORE_USER_SECTIONS)
_append_core_sections(1, CORE_SYSTEM_DEFS, _core_installed_sys, "system", CORE_SYSTEM_SECTIONS)

# --- TAB 7: PRESETS ---
# Empty – populated at runtime by User Presets via ENABLE_USER_PRESETS /
# USER_PRESETS_TAB="Presets" -> Reset to Defaults / Save as Preset / Import.
# No static presets needed; AI services (dusky_llm/stt) now live in Core User.


# =============================================================================
# DEFERRED FULL FETCH (Tabs 2-6)
# Background threads start immediately (running in parallel with TUI startup).
# The TUI calls DEFERRED_LOAD() after initial render to complete these tabs.
# =============================================================================
def _fetch_all_unit_files(scope: str) -> tuple[set, set, set]:
    """Returns (installed_services, enabled_services, installed_timers) in a single pass."""
    call = [
        "systemctl",
        "list-unit-files",
        "--type=service,timer",
        "--no-pager",
        "--no-legend",
    ]
    if scope == "user":
        call.insert(1, "--user")

    installed_srv = set()
    enabled_srv = set()
    installed_tmr = set()

    try:
        res = subprocess.run(
            call, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        for line in res.stdout.splitlines():
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            unit, state = parts[0], parts[1]

            if unit.endswith(".service"):
                installed_srv.add(unit)
                if state == "enabled":
                    enabled_srv.add(unit)
            elif unit.endswith(".timer"):
                installed_tmr.add(unit)

        return installed_srv, enabled_srv, installed_tmr
    except Exception as e:
        import sys

        print(
            f"[tui_service_toggle] ERROR: _fetch_all_unit_files({scope}): {e}",
            file=sys.stderr,
        )
        return set(), set(), set()


def _fetch_active_services(scope: str) -> set:
    call = [
        "systemctl",
        "list-units",
        "--type=service",
        "--state=active",
        "--no-pager",
        "--no-legend",
    ]
    if scope == "user":
        call.insert(1, "--user")
    try:
        res = subprocess.run(
            call, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        return {line.split()[0] for line in res.stdout.splitlines() if line}
    except Exception as e:
        import sys

        print(
            f"[tui_service_toggle] ERROR: _fetch_active_services({scope}): {e}",
            file=sys.stderr,
        )
        return set()


# Start full fetch in background IMMEDIATELY — these threads run in parallel
# with TUI startup so they're often already finished by the time DEFERRED_LOAD is called.
_bg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
_f_user_all = _bg_executor.submit(_fetch_all_unit_files, "user")
_f_sys_all = _bg_executor.submit(_fetch_all_unit_files, "system")
_f_user_act = _bg_executor.submit(_fetch_active_services, "user")
_f_sys_act = _bg_executor.submit(_fetch_active_services, "system")


def DEFERRED_LOAD() -> list[int]:
    """
    Completes the deferred tab population for tabs 2-6.
    Waits on background futures (which have been running since module import),
    then populates the SCHEMA lists.
    Returns list of tab indices that were populated.
    Called by the TUI after its initial render of tabs 0-1.
    """
    installed_user_srv, enabled_user, timers_user = _f_user_all.result()
    installed_sys_srv, enabled_sys, timers_sys = _f_sys_all.result()
    active_user_raw = _f_user_act.result()
    active_sys_raw = _f_sys_act.result()
    _bg_executor.shutdown(wait=False)

    installed_user = installed_user_srv | timers_user
    installed_sys = installed_sys_srv | timers_sys

    active_user = active_user_raw.intersection(installed_user_srv)
    active_sys = active_sys_raw.intersection(installed_sys_srv)

    # Track used units (core tabs already populated, avoid duplicates in "All" tabs)
    used_user = {unit for unit in CORE_USER_DEFS if unit in _core_installed_user}
    used_sys = {unit for unit in CORE_SYSTEM_DEFS if unit in _core_installed_sys}

    # --- TAB 2: ACTIVE SERVICES ---
    for unit in sorted(active_user):
        if "@" in unit:
            continue
        SCHEMA[2].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="user",
                type_="bool",
                default=False,
                group="User Services",
                extended_help=f"**Unit:** `{unit}`\n**Scope:** User\n\nCurrently active user-level service.",
            )
        )

    for unit in sorted(active_sys):
        if "@" in unit:
            continue
        SCHEMA[2].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="system",
                type_="bool",
                default=False,
                group="System Services",
                extended_help=f"**Unit:** `{unit}`\n**Scope:** System\n\nCurrently active system-level service.",
            )
        )

    # --- TAB 3: ENABLED SERVICES ---
    for unit in sorted(enabled_user):
        if "@" in unit:
            continue
        SCHEMA[3].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="user",
                type_="bool",
                default=False,
                group="User Services",
                extended_help=f"**Unit:** `{unit}`\n**Scope:** User\n\nEnabled to start automatically on boot.",
            )
        )

    for unit in sorted(enabled_sys):
        if "@" in unit:
            continue
        SCHEMA[3].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="system",
                type_="bool",
                default=False,
                group="System Services",
                extended_help=f"**Unit:** `{unit}`\n**Scope:** System\n\nEnabled to start automatically on boot.",
            )
        )

    # --- TAB 4: TIMERS ---
    for unit in sorted(timers_user):
        SCHEMA[4].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="user",
                type_="bool",
                default=False,
                group="User Timers",
                extended_help=f"**Unit:** `{unit}`\n**Scope:** User\n\nSystemd timer unit (Cron alternative).",
            )
        )
        used_user.add(unit)

    for unit in sorted(timers_sys):
        SCHEMA[4].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="system",
                type_="bool",
                default=False,
                group="System Timers",
                extended_help=f"**Unit:** `{unit}`\n**Scope:** System\n\nSystemd timer unit (Cron alternative).",
            )
        )
        used_sys.add(unit)

    # --- TAB 5: ALL USER ---
    for unit in sorted(installed_user - used_user):
        if "@" in unit or not unit.endswith(".service"):
            continue
        SCHEMA[5].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="user",
                type_="bool",
                default=False,
                group=unit[0].upper(),
                extended_help=f"**Unit:** `{unit}`\n**Scope:** User\n\nAuto-discovered service.",
            )
        )

    # --- TAB 6: ALL SYSTEM ---
    for unit in sorted(installed_sys - used_sys):
        if "@" in unit or not unit.endswith(".service"):
            continue
        SCHEMA[6].append(
            ConfigItem(
                label=unit,
                key=unit,
                scope="system",
                type_="bool",
                default=False,
                group=unit[0].upper(),
                extended_help=f"**Unit:** `{unit}`\n**Scope:** System\n\nAuto-discovered service.",
            )
        )

    return [2, 3, 4, 5, 6]

# =============================================================================
# DIRECT EXECUTION HANDLER
# =============================================================================
if __name__ == "__main__":
    import sys, subprocess
    from pathlib import Path

    script_path = Path(__file__).resolve()
    main_router = Path.home() / "user_scripts" / "dusky_tui" / "python" / "main" / "main.py"

    if main_router.exists():
        sys.exit(subprocess.run([sys.executable, str(main_router), str(script_path)] + sys.argv[1:]).returncode)
    else:
        print(f"[-] Error: Main Dusky TUI router not found at {main_router}", file=sys.stderr)
        sys.exit(1)
