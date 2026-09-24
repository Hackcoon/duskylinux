Reviewed and updated `dusky_snapshot_manager.py` to 3.3.1 on 2026-09-25.

Verified locally on kernel 7.3.0-rc4-dusky-battery, Python 3.14.7,
btrfs-progs 7.1, Snapper 0.13.2, util-linux 2.42.4, systemd 261.3,
and fzf 0.74.4. The target kernel minimum is 7.2. No older-package
compatibility path was added.

Confirmed defects addressed:

- Installed Btrfs subvolume commands reject JSON, and `get-default -- PATH`
  treats `--` as the path. Removed the failed-command/fallback sequence.
- Filesystem sync and directory fsync failures were ignored; durable writes
  also assumed a single write consumed every byte.
- Cross-filesystem restores had only one journal copy. Every participant now
  receives a record; recovery follows the authoritative coordinator, checks
  exact IDs, and persists unwind intent before changing paths.
- Cleanup compared a default ID captured at scheduling time and deleted by
  pathname without validating the recorded identity. Generated services now
  use a bundled copy of the checked cleanup implementation, with locking,
  current mount/default checks, and transaction checks.
- Undo did not repair the default subvolume or journal its exchange. It now
  does both, sorts candidates by timestamp, and preserves both candidates
  when an interrupted undo is aborted.
- Backup temporary objects were exposed to concurrent cleanup. Transfers now
  hold the lock through child-process termination and staging cleanup.
- Moving a read-only received subvolume between directories failed with
  EROFS. Backups now publish their container directory and return
  `dusky_backup_<label>_<timestamp>/snapshot`, preserving received UUIDs.
- Incremental receive could not reach parents outside the destination's
  mounted subvolume. Receive now operates through a verified top-level mount.
- Forwarding received backups compared local UUIDs with stream UUIDs and
  rejected valid transfers. Source and incremental-parent checks now use the
  original received UUID when present.
- Mount-table errors could be mistaken for an idle filesystem. Bind and
  shadowed mounts now use their recorded subvolume IDs.
- Missing tagged snapshot partners could silently select unrelated snapshots.
- Fstab/rootflags parsing missed numeric subvolume references. Restore rejects
  numeric pins affecting its targets, including those in the restored fstab.
- Kernel checks treated `vmlinuz-linux` as a release number. External images
  are compared with kernel images in the restored modules tree instead.
- Snapper configurations and snapshot columns are now queried explicitly;
  fzf execution errors and conflicting CLI options are reported accurately.

First-pass validation (3.3.0):

- `python -m unittest discover -s tests -v`: 10 regression tests.
- `sudo python tests/integration_btrfs.py`: real Btrfs operations on two
  disposable loop filesystems in a private mount namespace. Covers exchanges,
  defaults, replicated journals, interrupted staging, partial activation,
  recovery through a secondary filesystem, restore, undo, aborted undo,
  initial replication interruption, cleanup guards, full/incremental backups,
  writable sources, received-subvolume forwarding, and destination subvolume mounts. Fixtures are removed.
- Generated units checked with `systemd-analyze verify`.
- Real fzf TUI launch/Escape smoke test passed.
- Read-only checks correctly listed the existing root/home mounts and all
  eight Snapper snapshots. Existing snapshots were not modified.

Limits: interrupted states were constructed on real filesystems; physical
power cuts and rebooting into a restored root were not tested. Exchanges
are atomic per subvolume, not across a pair. Interrupted restores require
explicit `--recover` or `--recover --abort`; there is no automatic boot
recovery service. UKIs require a separate consistency check and are reported
as such. These results do not establish correctness on unreleased future
kernels or packages.

References checked alongside installed manual pages:
[Btrfs subvolumes](https://btrfs.readthedocs.io/en/latest/btrfs-subvolume.html),
[Btrfs receive](https://btrfs.readthedocs.io/en/latest/btrfs-receive.html),
[Snapper](https://man.archlinux.org/man/extra/snapper/snapper.8.en), and
[upstream Btrfs rename implementation](https://github.com/torvalds/linux/blob/master/fs/btrfs/inode.c).

Second pass (3.3.1):

- Reproduced deletion of mounted receive staging on disposable Btrfs.
  Staging cleanup now checks mounted/default IDs, rejects unexpected objects,
  waits for deletion to commit, and reports incomplete cleanup.
- Restricted staging sweeps to the filesystem whose journals were checked;
  deduplicated directory aliases and rejected symlink staging paths.
- Reproduced a repeated restore targeting the retired but still mounted root.
  Restore now requires reboot/remount before targeting that transient path.
- Remaining journals block mutations even when a replica says finalised;
  recovery must reconcile the coordinator before removing those records.
- Qualified mounted-path labels by filesystem UUID to distinguish identical
  subvolume names on separate filesystems.
- Tightened pairing: heuristic candidates must match type and description,
  and cannot belong to another tagged pair. Selected metadata is rechecked.
- Reproduced an exception leaving half a Snapper pair. Creation now attempts
  compensation for both tagged halves on exceptions and reports failures.
  Snapshot creation has no arbitrary subprocess timeout. Pair deletion
  validates both IDs before deleting either and reports partial completion.
- Removed unused state and kept logging transport tracebacks out of normal
  terminal output; DUSKY_DEBUG retains diagnostic logging errors.

Second-pass validation:

- All 17 unit regression tests passed.
- The real Btrfs integration suite passed again.
- The real Snapper suite passed: create/list/pair/delete, second-config
  failure, and an injected exception during second-half creation.
- The stress suite passed 59 SIGKILL scenarios after journal writes, syncs,
  renames, and default changes during activation, unwind, and finalisation.
  Recovery checked both filesystems' contents, defaults, and journal removal.
  Mounted staging, repeated restore, and stacked mount checks also passed.
- Python compilation and Ruff F checks passed for the manager.

The Snapper fixture now bind-mounts private configuration directories in its
private mount namespace. An initial attempt using Snapper --root created
temporary host config entries named left/right; these were identified by
their exact temporary subvolume paths and removed, and SNAPPER_CONFIGS was
restored to root/home. Existing root/home snapshots were not modified.

These crash tests terminate processes after completed operations; they do
not simulate lost storage writes or physical power loss. A restored-root
reboot and ISO boot integration remain untested.
