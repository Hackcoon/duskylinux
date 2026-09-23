# Dusky kernel compiler

Arch Linux, x86-64, Linux 7.2+, Python 3.14+, LLVM 21+ or current GCC. Keep this directory together: the engine loads its schema, runtime helper and optional patch files from adjacent paths.

```sh
python3 dusky_kernal_compile.py                         # Interactive menu
python3 dusky_kernal_compile.py --doctor
python3 dusky_kernal_compile.py -p battery --wizard      # Review/override any exposed tuning option
python3 dusky_kernal_compile.py -p battery --no-install  # Build packages without installation
python3 dusky_kernal_compile.py -p battery --configure-only --print-matrix
```

A build prompts to install missing Arch build dependencies and, when needed, modprobed-db from AUR. `--yes` authorizes automatic dependency installation. Strict pruning needs a census collected on the target with its relevant hardware/peripherals in use. The bundled `modules/modprobed.db` is never selected automatically for another machine.

## Profiles and patches

Only TOML files in `kernel_profiles/` and the user's XDG profile directory are selectable. No named preset is embedded in the engine. `kernel_profiles/schema.py` contains field defaults, validation limits and wizard metadata. `--write-default-profiles` creates a new `custom.toml` without overwriting an existing file. `--spec` prints the schema; `--show --dump-toml -p NAME` prints a fully resolved profile.

The battery profile tracks mainline, including release candidates. Select `release.channel = "stable"` or `release.pin` to change that. CPU names accepted by the selected compiler work without updating a script allowlist. Use `cpu.arch = "native"` for a local build. `cpu.march` accepts additional `-march=CPU` and `-mtune=CPU` overrides.

At each interactive build, the release picker lists the current mainline, stable and longterm entries from kernel.org, with the profile's channel or pin preselected. Choose another listed release for this build without changing the profile file. An explicit RC choice works even when `release.allow_rc = false`; that setting controls automatic selection. `--pin VERSION` bypasses the picker, while `--yes` or unattended builds use the profile's pin or newest allowed release in its channel. Versions below the compiler's 7.2 minimum appear as unavailable, including current older LTS branches. The feed lists current channel releases, not every historical patch release; use `--pin VERSION` for an older supported version.

If a source download fails, interactive builds offer retry, alternate host (when available), or cancel. Kernel.org partial downloads can resume. The GitHub release-candidate fallback does not support byte-range resume, so retrying that host restarts its transfer; switching back to kernel.org retains its separate partial download.

All performance patches are optional: `dusky.patch_sched_inline`, `dusky.patch_evdev_rcu`, `dusky.patch_pci_pme`, `compiler.polly`, and `boot.acs_override`. New profiles default to no enhancement patches. Existing battery selections are retained. Patches must apply with zero fuzz; incompatible optional patches are reported and skipped. Scheduler patches have their separate `require_patch` / `allow_vanilla_fallback` controls. No patch is required for vanilla EEVDF, native CPU tuning or LTO. O3 uses compiler flags rather than a source patch with unrelated optimization changes.

The new NTFS driver is selected by `storage.extra_filesystems = ["ntfs"]` (`CONFIG_NTFS_FS`). `ntfs3` remains a distinct driver choice for systems explicitly using it.

## Included profiles

All four default to **strict target-census pruning**, native local CPU targeting and ThinLTO. Imports replace native with the exported target CPU. Explicit keep lists and Kconfig overrides are still available for peripherals or workload features absent from the census.

| Profile | Intended use | Main tradeoffs |
|---|---|---|
| `battery` | Your existing tuned laptop setup | Keeps its gaming, VFIO, vendor-specific keep list and forced-ASPM choice. |
| `performance` | Responsive desktop and sustained performance | Performance governor/EPP, 1000 Hz, full preemption, THP on request, O2; increased power use. |
| `extreme_power` | Aggressive power saving | Power-focused CPU settings, 100 Hz, lazy preemption/RCU, aggressive ASPM without force; no IA32 or NTSync. |
| `low_memory` | Memory-constrained desktop | Size optimization, 250 Hz, smaller buffers, prompt RCU reclamation, ZSTD swap and stronger reclaim; no IA32, NTSync or hibernation. |

The three new profiles have no enhancement patches, scheduler daemon/BTF requirement, vendor-specific driver lists or forced PCIe ASPM. They retain the scalable SLUB allocator rather than forcing SLUB_TINY. Native O2 is intentional for performance: O3 is available, but does not universally improve workloads. No measured speed, wattage or idle-RAM targets are implied.

Pruning is not just blindly deleting modules: root filesystem support, essential userspace facilities and explicit profile features remain. Intel i915/xe selection follows the pruned target configuration; a missing census driver requires an explicit keep or a corrected census. Unselected TCP/qdisc implementations are no longer force-enabled. Automatic CPU/NUMA limits follow the target topology.

## Build elsewhere for an older computer

On the target:

```sh
python3 dusky_kernal_compile.py -p battery --export-bundle ~/target.tar.gz
```

On the build computer, import the bundled profile (or pass `-p NAME` to override it with a local profile):

```sh
python3 dusky_kernal_compile.py --import-bundle target.tar.gz
python3 dusky_kernal_compile.py -p remote_HOST --no-install
```

Import reports the exact generated profile name, such as `remote_oldpc_performance`. Package suffixes include both the source profile and target name, so target variants can coexist. Bundles require the current v3 format; re-export old bundles. They preserve CPU, memory, NUMA, GPU, filesystems, DKMS and module-census data. Unknown target CPUs fall back to the target's reported ISA level; export with Clang/GCC installed to capture the precise compiler CPU name. Remote builds automatically disable installation on the build computer. They cannot use `native` or fall back to the build computer's module list. Build parallelism uses the build computer's resources.

Copy the resulting kernel and headers packages to the target and install there:

```sh
python3 dusky_kernal_compile.py --install-pkg /path/to/linux-*.pkg.tar.zst
```

Saved packages carry their resolved profile, including boot-entry preferences. Headers are required for target DKMS modules. Exact CPU targeting is for that target computer, not a general-purpose binary kernel.

## Optional RAM builds and persistent storage

Edit `kernel_profiles/settings/kernel_settings.toml` for machine storage policy; keep kernel tuning in the profile. `--settings FILE` selects another settings file. Empty persistent paths default to `~/.cache/dusky-kernel` (respecting XDG_CACHE_HOME).

- `persistent_dir`: saved source trees, object files, seeds, downloads and patches.
- `packages_dir`: completed packages; defaults to `persistent_dir/packages`.
- `ccache_dir` / `thinlto_dir`: persistent compiler/linker caches.
- `zram_dir`: optional RAM workspace; defaults to `/mnt/zram1/dusky_kernel`.
- `ram_reserve_gib`: memory withheld from automatic job sizing for additional RAM-filesystem growth (default 8 GiB). It is a planning allowance, not an enforced memory limit.

Every interactive build with an available RAM mount asks **Use RAM workspace? [y/N]**, even with `--yes` or `--no-prompt`. Declining builds on disk. Noninteractive runs default to disk; `--ram-build` explicitly chooses RAM. The script never creates or reformats a RAM device. `--build-dir` overrides the persistent root, not the RAM workspace.

RAM mode restores source/object files and compiler/linker caches, preserving timestamps, then checkpoints changed files to disk on completion, failure or Ctrl-C. Let the save finish before rebooting. Interrupted saves leave an `.unsaved` marker and block an older disk copy from overwriting the RAM work. Packages are written directly to persistent storage. Disposable package staging files are excluded from checkpoints. Downloads and patch caches stay on disk.

A power loss, forced kill or reboot before checkpoint completion can lose new RAM-only work. Checkpointing writes changed output to disk, so this reduces intermediate write traffic rather than eliminating SSD writes. Switching between disk and RAM paths can invalidate some build/cache entries; repeated builds at the same path have the best reuse. Restoring many saved kernels/caches also consumes RAM and startup time.

The mount name does not establish its storage type: `/mnt/zram1` on the audited machine is **tmpfs**. Tmpfs can swap; systems with disk-backed swap can therefore still write to the SSD. Choose disk on memory-constrained systems. Manual `compiler.jobs` overrides remain your responsibility.

## Runtime tuning

`runtime.enabled` controls a packaged, kernel-specific systemd service. It applies EPP/governor, VM/network sysctls, THP/MGLRU/KSM settings, scheduler debugfs settings and block scheduling once at boot. Missing hardware interfaces are reported in the journal. Other power-management software can subsequently override these settings; this helper does not poll or fight it.

`runtime.manage_zram` creates compressed swap only when no ZRAM swap is already active. Existing swap is never reset or resized. Recompression support/algorithm selection does not periodically recompress pages. `scheduler.scx` optionally installs a separate scheduler service; it is not started for the battery profile's `none` selection. Package dependencies include the necessary runtime tools.

`boot.write_entries` controls systemd-boot entries; `boot.set_default` separately controls changing the default boot selection. GRUB/UKI installations retain their existing command-line integration. No runtime service is started on the build host during compilation.

## Validation

```sh
python -m unittest discover -s tests -v
```

See [the audit report](audit/AUDIT.md) for findings, source references, checks performed and remaining limits. Configuration checks do not establish runtime speed, battery life, DKMS compatibility or successful boot on untested hardware.
