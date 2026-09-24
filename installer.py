#!/usr/bin/env python3
"""
install_car_mod.py — MC3 Car Mod Installer (CLI)
=================================================
Uses dave_index.py for fast, reliable, in-place replacement.
No compression. No rebuild. No Slot Builder. No ELF hacks.

Just double-click this file (or run from terminal).

Folder layout:
  install_car_mod.py
  dave_index.py
  Workspace/
    ASSETS.DAT          <- archive to modify
  Mod_module/           <- drop all mod files here (any nesting allowed)

Usage:
  Double-click                              interactive install
  python install_car_mod.py --debug         preview only
  python install_car_mod.py --yes           skip confirmation
  python install_car_mod.py --car vp_xxx    only that car's files
  python install_car_mod.py --filter flash  only flash/*.pck
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# COLORS
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    os.system("")

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE  = SCRIPT_DIR / "Workspace"
MOD_FOLDER = SCRIPT_DIR / "Mod_module"
ASSETS_DAT = WORKSPACE / "ASSETS.DAT"

# File extensions we care about
WANTED_EXTS = (
    ".dat", ".pck", ".carcfg", ".mccarcustom", ".damage",
    ".mcgarage", ".camtrackcs", ".campovcs", ".mesh",
)


# ---------------------------------------------------------------------------
def is_wanted(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in WANTED_EXTS)


def scan_mod_folder() -> list:
    if not MOD_FOLDER.is_dir():
        return []
    return [p for p in MOD_FOLDER.rglob("*") if p.is_file() and is_wanted(p)]


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def find_matches(archive, local_files):
    """Match local files to archive entries by basename (case-insensitive)."""
    lookup = {}
    for name in archive.entries_by_name:
        base = name.split("/")[-1].lower()
        if base not in lookup:
            lookup[base] = name
        elif len(name) < len(lookup[base]):
            lookup[base] = name  # prefer shorter paths

    matched, unmatched = [], []
    for local in local_files:
        key = local.name.lower()
        if key in lookup:
            matched.append((local, lookup[key]))
        else:
            unmatched.append(local)

    return matched, unmatched


def show_summary(matched, unmatched):
    print()
    print(f"{CYAN}{'=' * 74}{RESET}")
    print(f"{CYAN}{BOLD}  🔍 Matched files (will be REPLACED){RESET}")
    print(f"{CYAN}{'=' * 74}{RESET}")
    print()
    if matched:
        for local, archive_name in sorted(matched, key=lambda x: x[1].lower()):
            size = human_size(local.stat().st_size)
            print(f"  {BOLD}📦 {local.name}{RESET}  {DIM}({size}){RESET}")
            print(f"     {DIM}→ {archive_name}{RESET}")
    else:
        print(f"{YELLOW}  ⚠️  No matches found.{RESET}")

    if unmatched:
        print()
        print(f"{YELLOW}{'=' * 74}{RESET}")
        print(f"{YELLOW}{BOLD}  ⏭️  Unmatched files (SKIPPED — not in archive){RESET}")
        print(f"{YELLOW}{'=' * 74}{RESET}")
        print()
        for local in sorted(unmatched, key=lambda x: x.name.lower()):
            rel = local.relative_to(MOD_FOLDER)
            print(f"  {DIM}• {rel}{RESET}")
    print()


def confirm(prompt="Proceed? (Y/N): "):
    try:
        return input(f"{BOLD}{prompt}{RESET}").strip().upper() == "Y"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="MC3 Car Mod Installer (uses dave_index.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python install_car_mod.py                       interactive install\n"
            "  python install_car_mod.py --debug               preview only\n"
            "  python install_car_mod.py --yes                 skip confirmation\n"
            "  python install_car_mod.py --car vp_d_diablo_98  only that car's files\n"
            "  python install_car_mod.py --filter flash        only flash/*.pck\n"
        ),
    )
    ap.add_argument("--debug",  action="store_true", help="preview only, do not modify")
    ap.add_argument("--yes", "-y", action="store_true", help="skip Y/N confirmation")
    ap.add_argument("--car",    help="only files whose name contains this (e.g. vp_d_diablo_98)")
    ap.add_argument("--filter", help="only files whose path contains this (e.g. flash)")
    args = ap.parse_args()

    # ---------- HEADER ----------
    print()
    print(f"{CYAN}{'=' * 74}{RESET}")
    print(f"{CYAN}{BOLD}  🚗  MC3 Car Mod Installer{RESET}")
    print(f"{CYAN}{'=' * 74}{RESET}")
    print(f"  Workspace : {WORKSPACE}")
    print(f"  Mod folder: {MOD_FOLDER}")
    print()

    # ---------- SANITY ----------
    if not ASSETS_DAT.is_file():
        print(f"{RED}❌ ASSETS.DAT not found in Workspace/{RESET}")
        print(f"   Expected: {ASSETS_DAT}")
        return 1

    if not MOD_FOLDER.is_dir():
        MOD_FOLDER.mkdir(parents=True)
        print(f"{YELLOW}⚠️  Mod_module/ was missing — created it.{RESET}")
        print(f"   Drop your car mod files into: {MOD_FOLDER}")
        return 1

    # ---------- IMPORT ----------
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from dave_index import DaveArchive, DaveArchiveError
    except ImportError:
        print(f"{RED}❌ dave_index.py not found in {SCRIPT_DIR}{RESET}")
        return 1

    # ---------- ZERO COMPRESSION ----------
    DaveArchive._is_compress_safe = lambda self, entry: False
    print(f"{GREEN}🔒 Compression disabled (car mods stay raw).{RESET}\n")

    # ---------- SCAN ----------
    print(f"{CYAN}📂 Scanning Mod_module/...{RESET}")
    local_files = scan_mod_folder()
    if not local_files:
        print(f"{YELLOW}⚠️  No mod files in Mod_module/.{RESET}")
        return 1
    print(f"   Found {len(local_files)} file(s)\n")

    # ---------- FILTERS ----------
    if args.car:
        needle = args.car.lower()
        local_files = [f for f in local_files if needle in f.name.lower()]
        print(f"{CYAN}🎯 Filter --car '{args.car}': {len(local_files)} file(s){RESET}")
    if args.filter:
        needle = args.filter.lower()
        local_files = [f for f in local_files
                       if needle in str(f.relative_to(MOD_FOLDER)).lower()]
        print(f"{CYAN}🎯 Filter --filter '{args.filter}': {len(local_files)} file(s){RESET}")

    if not local_files:
        print(f"{YELLOW}⚠️  Nothing matches the filters.{RESET}")
        return 1

    # ---------- OPEN ARCHIVE ----------
    print(f"\n📂 Opening archive: {ASSETS_DAT.name}")
    try:
        archive = DaveArchive(str(ASSETS_DAT))
    except DaveArchiveError as e:
        print(f"{RED}❌ Failed to open: {e}{RESET}")
        return 1
    print(f"✅ Loaded: {len(archive.entries)} entries\n")

    # ---------- MATCH ----------
    matched, unmatched = find_matches(archive, local_files)
    show_summary(matched, unmatched)

    if not matched:
        print(f"{RED}❌ No archive matches. Aborting.{RESET}")
        return 1

    # ---------- DEBUG MODE ----------
    if args.debug:
        print(f"{CYAN}🧪 Debug mode — nothing written.{RESET}")
        return 0

    # ---------- CONFIRM ----------
    if not args.yes:
        if not confirm(f"Install {len(matched)} file(s)? (Y/N): "):
            print(f"{YELLOW}👋 Cancelled.{RESET}")
            return 0

    # ---------- BACKUP ----------
    backup = ASSETS_DAT.with_name(ASSETS_DAT.name + ".backup")
    print()
    if not backup.exists():
        print(f"🛡️  Creating backup: {backup.name}")
        shutil.copy2(ASSETS_DAT, backup)
    else:
        print(f"🛡️  Backup exists: {backup.name}")

    # ---------- INSTALL ----------
    print()
    print(f"{CYAN}{'─' * 74}{RESET}")
    print(f"{CYAN}{BOLD}🔨 Installing...{RESET}")
    print(f"{CYAN}{'─' * 74}{RESET}")

    replaced = failed = 0
    for local, archive_name in matched:
        with open(local, "rb") as f:
            data = f.read()
        try:
            entry = archive.entries_by_name[archive_name]
            result = archive.replace_file(entry, data)
            print(f"  {GREEN}✅{RESET} {local.name}")
            print(f"     {DIM}→ {archive_name}  [{result}]{RESET}")
            replaced += 1
        except Exception as e:
            print(f"  {RED}❌{RESET} {local.name}: {e}")
            failed += 1

    # ---------- SAFETY ----------
    if archive._pending_additions:
        print(f"\n{RED}❌ Unexpected additions detected. Aborting save.{RESET}")
        print(f"   Restore from backup: {backup}")
        return 1

    # ---------- SAVE ----------
    print(f"\n💾 Saving via fast append...")
    try:
        archive.save_append(str(ASSETS_DAT))
    except Exception as e:
        print(f"{RED}❌ Save failed: {e}{RESET}")
        print(f"   Restore from backup: {backup}")
        return 1

    # ---------- VERIFY ----------
    print(f"\n{CYAN}🔍 Verifying .pck compression...{RESET}")
    try:
        verify = DaveArchive(str(ASSETS_DAT))
        bad = 0
        for local, archive_name in matched:
            if not local.name.lower().endswith((".pck", ".mesh.pck")):
                continue
            entry = verify.entries_by_name.get(archive_name)
            if entry and entry.is_compressed:
                print(f"  {RED}❌ {local.name}: COMPRESSED{RESET}")
                bad += 1
        if bad == 0:
            print(f"  {GREEN}✅ All .pck files stored UNCOMPRESSED{RESET}")
    except Exception as e:
        print(f"  {YELLOW}⚠️  Verify error: {e}{RESET}")

    # ---------- DONE ----------
    print()
    print(f"{CYAN}{'=' * 74}{RESET}")
    print(f"{GREEN}{BOLD}🎉  INSTALL COMPLETE!{RESET}")
    print(f"{CYAN}{'=' * 74}{RESET}")
    print()
    print(f"  ✅ Replaced : {replaced}")
    if failed:
        print(f"  ❌ Failed   : {failed}")
    print(f"  📁 Archive  : {ASSETS_DAT.name}")
    print(f"  🛡️  Backup   : {backup.name}")
    print()
    return 0


# ---------------------------------------------------------------------------
# ENTRY POINT — Always pauses before closing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}⚠️  Interrupted.{RESET}")
        exit_code = 1
    except Exception as e:
        print(f"\n{RED}❌ Unexpected error: {e}{RESET}")
        import traceback
        traceback.print_exc()
        exit_code = 1
    finally:
        print()
        print(f"{CYAN}{'─' * 74}{RESET}")
        try:
            input(f"{BOLD}Press Enter to exit...{RESET}")
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(exit_code)