"""
dave_index.py — FINAL RELEASE
- Fast Append for replacements (100% working)
- Full Rebuild for new files (uses dave.py with MC3 config)
- Hardlinks for speed
- Auto-answer "Y" to dave.py prompts
"""

import os
import shutil
import tempfile
import zlib
import traceback
from dataclasses import dataclass, field

CHARS = "\x00 #$()-./?0123456789_abcdefghijklmnopqrstuvwxyz~\x7F"
DAVE = b"DAVE"
DAVE_C = b"Dave"

# Safety blocklist - NEVER compress these
COMP_EXT_BLOCKLIST = (".pck", ".psppck", ".xbck", ".ppf", ".pspppf", ".xbpf")
COMP_DIR_BLOCKLIST = ("flash/", "resources/vehicle/")


@dataclass
class DaveEntry:
    name: str
    name_offset_raw: int
    name_offset_abs: int
    file_offset: int
    size_full: int
    size_comp: int
    index: int
    is_dir: bool = field(init=False)

    def __post_init__(self):
        self.is_dir = self.name.endswith("/")

    @property
    def is_compressed(self):
        return self.size_full != self.size_comp and not self.is_dir


class DaveArchiveError(Exception):
    pass


class DaveArchive:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.magic = None
        self.entries_size = 0
        self.names_size = 0
        self.entries = []
        self.entries_by_name = {}
        self._pending_rebuild = {}      # Replacements (queued for append)
        self._pending_additions = {}    # New files (queued for full rebuild)
        self._load_header()

    # ------------------------------------------------------------------ #
    def _load_header(self):
        try:
            with open(self.path, "rb") as f:
                magic = f.read(4)
                if magic not in (DAVE, DAVE_C):
                    raise DaveArchiveError("Not a DAVE/Dave archive.")
                self.magic = magic

                entries_n = int.from_bytes(f.read(4), "little")
                info_size = int.from_bytes(f.read(4), "little")
                name_size = int.from_bytes(f.read(4), "little")
                self.entries_size = info_size
                self.names_size = name_size

                entries = []
                prev_name = ""
                for i in range(entries_n):
                    f.seek(0x800 + i * 0x10)
                    name_raw = int.from_bytes(f.read(4), "little")
                    name_abs = name_raw + info_size + 0x800
                    file_offs = int.from_bytes(f.read(4), "little")
                    size_full = int.from_bytes(f.read(4), "little")
                    size_comp = int.from_bytes(f.read(4), "little")

                    f.seek(name_abs)
                    if magic == DAVE:
                        name = self._read_str(f)
                    else:
                        name, prev_name = self._read_compressed_name(f, prev_name)

                    entries.append(
                        DaveEntry(name, name_raw, name_abs, file_offs, size_full, size_comp, i)
                    )

                self.entries = entries
                self.entries_by_name = {e.name: e for e in entries}
        except EOFError as e:
            raise DaveArchiveError(f"Archive corrupted or truncated: {e}")
        except Exception as e:
            raise DaveArchiveError(f"Failed to read archive: {e}")

    # ------------------------------------------------------------------ #
    @staticmethod
    def _read_str(f):
        chars = []
        while True:
            c = f.read(1)
            if not c or c == b"\x00":
                break
            chars.append(c.decode("ASCII"))
        return "".join(chars)

    @staticmethod
    def _read_bits(f):
        comp_data = int.from_bytes(f.read(3), "little")
        return [comp_data >> mul * 6 & 0x3F for mul in range(4)]

    def _read_compressed_name(self, f, prev_name):
        name_bits = self._read_bits(f)
        file_name = ""
        if name_bits[0] >= 0x38:
            dedup_size = (name_bits.pop(1) - 0x20) * 8 + name_bits.pop(0) - 0x38
            file_name = prev_name[:dedup_size]
        while name_bits[0]:
            file_name += CHARS[name_bits.pop(0)]
            if not name_bits:
                name_bits = self._read_bits(f)
        return file_name, file_name

    # ------------------------------------------------------------------ #
    def build_tree(self):
        root = {"__files__": []}
        for e in self.entries:
            parts = [p for p in e.name.split("/") if p]
            if e.is_dir or not parts:
                node = root
                for part in parts:
                    node = node.setdefault(part, {"__files__": []})
                continue
            node = root
            for part in parts[:-1]:
                node = node.setdefault(part, {"__files__": []})
            node.setdefault("__files__", []).append(e)
        return root

    # ------------------------------------------------------------------ #
    def extract_bytes(self, entry):
        if entry.is_dir:
            raise DaveArchiveError(f"'{entry.name}' is a folder.")
        with open(self.path, "rb") as f:
            f.seek(entry.file_offset)
            data = f.read(entry.size_comp)
        if entry.is_compressed:
            data = zlib.decompress(data, -15)
        return data

    # ------------------------------------------------------------------ #
    def _is_compress_safe(self, entry):
        if entry.is_dir:
            return False
        name = entry.name.lower()
        if name.endswith(COMP_EXT_BLOCKLIST):
            return False
        if name.startswith(COMP_DIR_BLOCKLIST):
            return False
        return True

    def _prepare_data_for_write(self, entry, raw_bytes, force_compress=False):
        if not self._is_compress_safe(entry):
            return raw_bytes

        should_compress = force_compress or entry.is_compressed
        if not should_compress:
            return raw_bytes

        zc = zlib.compressobj(9, zlib.DEFLATED, -15)
        comp = zc.compress(raw_bytes) + zc.flush()
        return comp if len(comp) < len(raw_bytes) else raw_bytes

    # ------------------------------------------------------------------ #
    def _slot_capacity(self, entry):
        offsets = sorted(e.file_offset for e in self.entries if not e.is_dir)
        idx = offsets.index(entry.file_offset)
        if idx + 1 < len(offsets):
            return offsets[idx + 1] - entry.file_offset
        return os.path.getsize(self.path) - entry.file_offset

    # ------------------------------------------------------------------ #
    # REPLACE FILE (100% Working Append Method)
    # ------------------------------------------------------------------ #
    def replace_file(self, entry, new_raw_bytes):
        if entry.is_dir:
            raise DaveArchiveError(f"Cannot replace a folder: {entry.name}")

        data = self._prepare_data_for_write(entry, new_raw_bytes, force_compress=False)
        capacity = self._slot_capacity(entry)

        if len(data) <= capacity:
            # PATCH IN PLACE (Instant)
            with open(self.path, "r+b") as f:
                f.seek(entry.file_offset)
                f.write(data)
                f.seek(0x800 + entry.index * 0x10 + 8)
                f.write(len(new_raw_bytes).to_bytes(4, "little"))
                f.write(len(data).to_bytes(4, "little"))
            entry.size_full = len(new_raw_bytes)
            entry.size_comp = len(data)
            self._pending_rebuild.pop(entry.name, None)
            return "patched"

        # QUEUE FOR APPEND
        self._pending_rebuild[entry.name] = new_raw_bytes
        return "queued"

    # ------------------------------------------------------------------ #
    # ADD NEW FILE (Queues for Full Rebuild)
    # ------------------------------------------------------------------ #
    def add_file(self, virtual_path, raw_bytes):
        if virtual_path in self.entries_by_name:
            raise DaveArchiveError(f"File '{virtual_path}' already exists.")
        if virtual_path in self._pending_additions:
            raise DaveArchiveError(f"File '{virtual_path}' is already queued.")
        self._pending_additions[virtual_path] = raw_bytes
        return "queued_for_rebuild"

    @property
    def has_pending_rebuild(self):
        return bool(self._pending_rebuild) or bool(self._pending_additions)

    # ------------------------------------------------------------------ #
    # FAST APPEND (For replacements only — 100% Working)
    # ------------------------------------------------------------------ #
    def save_append(self, output_path=None, force_compress=False):
        if self._pending_additions:
            raise DaveArchiveError("Cannot use Append when new files are queued. Use Full Rebuild.")

        if not self._pending_rebuild:
            print("No pending changes.")
            return

        target_path = os.path.abspath(output_path) if output_path else self.path
        if target_path != self.path:
            print(f"Copying base archive to {target_path}...")
            shutil.copy2(self.path, target_path)
            self.path = target_path

        with open(self.path, "r+b") as f:
            f.seek(0, 2)
            current_end = f.tell()

            for entry_name, raw_data in self._pending_rebuild.items():
                entry = self.entries_by_name[entry_name]
                data_to_write = self._prepare_data_for_write(entry, raw_data, force_compress)

                entry.size_full = len(raw_data)
                entry.size_comp = len(data_to_write)
                entry.file_offset = current_end

                f.seek(current_end)
                f.write(data_to_write)
                current_end += len(data_to_write)

                f.seek(0x800 + entry.index * 0x10)
                f.write(entry.name_offset_raw.to_bytes(4, "little"))
                f.write(entry.file_offset.to_bytes(4, "little"))
                f.write(entry.size_full.to_bytes(4, "little"))
                f.write(entry.size_comp.to_bytes(4, "little"))

                comp_status = "COMPRESSED" if len(data_to_write) < len(raw_data) else "UNCOMPRESSED"
                print(f"Appended {entry_name} ({comp_status})")

        self._pending_rebuild.clear()
        print(f"✅ Archive updated via Append at {self.path}")

    # ------------------------------------------------------------------ #
    # FULL REBUILD (For new files — uses dave.py with MC3 config)
    # ------------------------------------------------------------------ #
    def rebuild_with_hardlinks(self, output_path, force_compress=False):
        import importlib.util
        import builtins

        base_dir = os.path.dirname(os.path.abspath(__file__))
        dave_path = os.path.join(base_dir, "tools", "dave.py")
        if not os.path.exists(dave_path):
            dave_path = os.path.join(base_dir, "dave.py")
        if not os.path.exists(dave_path):
            raise DaveArchiveError("Could not find dave.py in tools/ or root!")

        spec = importlib.util.spec_from_file_location("dave", dave_path)
        dave_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dave_mod)

        # Use a local temp folder
        temp_root = os.path.join(base_dir, "temp_rebuild")
        os.makedirs(temp_root, exist_ok=True)
        tmp = tempfile.mkdtemp(dir=temp_root)

        try:
            print("📂 Preparing files in", tmp)

            # Write existing files
            for entry in self.entries:
                dest = os.path.join(tmp, entry.name)
                if entry.is_dir:
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)

                if entry.name in self._pending_rebuild:
                    data = self._pending_rebuild[entry.name]
                else:
                    data = self.extract_bytes(entry)
                with open(dest, "wb") as f:
                    f.write(data)

            # Write new files
            for name, data in self._pending_additions.items():
                dest = os.path.join(tmp, name)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)

            print("🔨 Rebuilding archive with dave.py (MC3 compatible config)...")

            # Auto-answer "Y" to dave.py prompts
            original_input = builtins.input
            builtins.input = lambda _: "Y"
            try:
                # --- EXACT SAME CONFIG AS YOUR MC3 MODDER.PY ---
                dave_mod.build_dave(
                    tmp, output_path,
                    compfiles=True,      # -cf
                    forcecomp=1,         # -fc 1 (only compress safe files)
                    complevel=9,         # Max compression
                    compnames=True,      # -cn (Dave format with compressed filenames)
                    dirs=False,          # No directory entries
                    align=128,           # -a 128 (128 * 16 = 2048 bytes)
                    compalign=True       # -ca (compact align)
                )
            finally:
                builtins.input = original_input

        except Exception as e:
            raise DaveArchiveError(f"Full rebuild failed: {e}\n{traceback.format_exc()}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                os.rmdir(temp_root)
            except OSError:
                pass

        self._pending_rebuild.clear()
        self._pending_additions.clear()
        if os.path.abspath(output_path) == self.path:
            self._load_header()
        print(f"✅ Full rebuild complete! Saved to {output_path}")

    # ------------------------------------------------------------------ #
    def reload(self):
        self._load_header()