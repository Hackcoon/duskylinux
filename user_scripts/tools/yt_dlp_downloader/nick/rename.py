#!/usr/bin/env python3
"""
Smart File Renamer for YTDLP Media Organization in /mnt/zram1/dusky_ytdlp/*
Renames files to "EPISODE_NUMBER.EXTENSION" format (e.g., 1687.m4a) based on episode identifiers.
ONLY processes files containing 'America First Ep.' pattern. Files without valid patterns are skipped with clear warnings.
"""

import os
import re
from pathlib import Path
import sys

# Configuration: Override directory via DSUSKY_YTDLP_DIR environment variable
SOURCE_DIR = os.environ.get("DSUSKY_YTDLP_DIR", "/mnt/zram1/dusky_ytdlp/")
ALLOWED_EXTENSIONS = {'.mp4', '.m4a', '.mp3', '.wav', '.webm'}  # Valid media extensions (with leading dot)

def extract_episode_identifier(filename):
    """Extracts integer episode ID and extension from filename.
    Only matches: 'America First Ep.<number>' case-insensitively.
    Returns (int_episode_id, '.ext') if valid; else None.
    Files without this pattern are skipped by caller with clear warning."""
    # Primary pattern: Explicit episode reference in filename
    pattern = r'America First Ep\. (\d+)'
    match = re.search(pattern, filename, re.IGNORECASE)
    if match:
        episode_id = int(match.group(1))
        ext = get_valid_extension(filename)
        # Basic sanity check (redundant but explicit; episode ID should be positive integer)
        return episode_id, ext if ext and episode_id > 0 else None
    return None  # No valid pattern found — caller skips with warning

def get_valid_extension(filename):
    """Reliably extracts standard media/audio extension from filename.
    Uses pathlib's suffix (includes leading dot) for accurate last-component extraction.
    Returns original-case '.ext' if in ALLOWED set; else None."""
    suffix = Path(filename).suffix  # e.g., '.mp4', '' or inconsistent casing like 'MP4'
    if not suffix:
        return None
    lower_suffix = suffix.lower()
    if lower_suffix in ALLOWED_EXTENSIONS:
        return f"{suffix}"  # Preserve original case from filename (filesystem-friendly)
    return None

def main():
    print("=" * 70)
    print(f"[INFO] Smart File Renamer")
    print(f"Target Directory: {SOURCE_DIR}")
    print("=" * 70)

    # Validate directory exists
    directory = Path(SOURCE_DIR).resolve()
    if not directory.is_dir():
        print(f"\n[ERROR] Source directory does not exist:\n{directory}\n")
        sys.exit(1)

    renamed = []       # [(source_path, new_filename)] ready for renaming
    skipped = {"no_pattern": [], "existing_file": []}  # Categorized skips only — no dead categories
    files_scanned = 0

    print(f"\n[*] Scanning directory contents...")
    for item in sorted(directory.iterdir()):
        if not item.is_file():
            continue

        filename = item.name
        files_scanned += 1
        old_path = item  # Preserve full Path object for accurate rename operations later

        result = extract_episode_identifier(filename)  # Returns tuple OR None per design
        if result is None:
            skipped["no_pattern"].append((filename, 
                "No valid episode pattern detected; requires 'America First Ep. <number>'"))
            print(f"[SKIP] {filename} | Reason: No valid episode pattern")
            continue
        ep_id, ext = result  # Now safe to unpack confirmed tuple

        if ep_id is None:
            skipped["no_pattern"].append((filename, "No valid episode pattern detected; requires 'America First Ep. <number>'"))
            print(f"[SKIP] {filename} | Reason: No valid episode pattern")
            continue

        # Construct target name and validate extension validity (redundant but explicit)
        new_name = f"{ep_id}{ext}"  # e.g., "1687" + ".m4a" → "1687.m4a"
        target_path = directory / new_name

        if target_path.exists():
            skipped["existing_file"].append((filename, f"Target name '{new_name}' already exists; skipping to avoid overwrite"))
            print(f"[SKIP] {filename} | Reason: Target name '{new_name}' exists")
            continue

        # Queue for renaming during execution phase (dry-run report shows planned action)
        renamed.append((old_path, new_name))

    # ===== DRY RUN REPORTING =====
    print(f"\n{'='*70}")
    print("RENAMING SUMMARY")
    print(f"Total files scanned: {files_scanned}")
    if renamed:
        print("\n[+] Files prepared for renaming:")
        for old, new in renamed:
            # Report full source path and intended destination filename
            source = f"{directory.parent}/{old}" if directory.is_absolute() else str(old)
            print(f"   → {new} (from: {old})")
    else:
        print("   (No files successfully prepared)")

    # Report skips clearly — only two real categories remain
    if skipped["no_pattern"]:
        print("\n[!] Files SKIPPED - No Valid Episode Pattern:")
        for name, reason in sorted(skipped["no_pattern"]):
            print(f"   ⚠️ {name} | {reason}")

    if skipped["existing_file"]:
        print("\n[!] Files SKIPPED - Target Name Already Exists:")
        for name, reason in sorted(skipped["existing_file"]):
            print(f"   ⚠️ {name} | {reason}")

    # ===== USER CONFIRMATION & EXECUTION =====
    total_to_rename = len(renamed)
    print("\n" + "="*70)

    if total_to_rename > 0:
        # Use descriptive format — no reliance on undefined variables from prior logic
        confirm_prompt = (f"[CONFIRM] Proceed with renaming {total_to_rename} files "
                           f"(new name format: EPISODE_NUMBER.EXTENSION, e.g., '1687.m4a')?")
        print(confirm_prompt)
        user_input = input("(Type 'yes' or 'no'): ").strip().lower()

        if user_input in ('yes', 'y'):
            success, failure = 0, 0
            for old_path, new_name in renamed:
                try:
                    os.rename(old_path, directory / new_name)
                    print(f"[OK] Renamed → {new_name}")
                    success += 1
                except PermissionError as e:
                    failure += 1
                    print(f"[FAIL] Permission denied on target in {directory}: {e}\n")
                except FileNotFoundError as e:
                    failure += 1
                    print(f"[FAIL] Source file missing during rename ({old_path}): {e}\n")
                except Exception as e:
                    failure += 1
                    print(f"[FAIL] Unexpected error renaming '{new_name}': {type(e).__name__}: {e}\n")
            # Final summary and exit code reflects success of operation
            print("\n" + "="*70)
            print("PROCESSING COMPLETE")
            print(f"Success: {success} | Failed: {failure}")
            if failure == 0 and success > 0:
                print("Directory now organized with concise episode-numbered filenames.")
                sys.exit(0)  # Success exit code for pipeline compatibility
            elif failure > 0:
                sys.exit(1)  # Non-zero exit to signal partial/full failure
        else:
            print("[CANCEL] Renaming aborted by user.\n")
    else:
        print("\n[INFO] No files were renamed in dry run. Directory remains unchanged.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Process cancelled by user (Ctrl+C). Exiting safely.\n")
        sys.exit(130)  # Standard exit code for interrupts
