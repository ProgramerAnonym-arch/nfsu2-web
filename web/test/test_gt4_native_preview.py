"""Synthetic checks for the non-installing native car-record preview."""
import importlib.util
from pathlib import Path
import struct
import unittest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "gt4-addon-native-preview.py"
spec = importlib.util.spec_from_file_location("native_preview", TOOL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def chunk(tag, body):
    return struct.pack("<II", tag, len(body)) + body


def car_record(name, index):
    buf = bytearray(mod.TYPE)
    buf[:len(name)] = name.encode()
    buf[0x20:0x20 + len(name)] = name.encode()
    geometry = f"CARS\\{name}\\GEOMETRY.BIN".encode()
    buf[0x40:0x40 + len(geometry)] = geometry
    buf[0xc0:0xc5] = b"HONDA"
    struct.pack_into("<I", buf, 0xd0, mod.hash_name(name))
    struct.pack_into("<I", buf, 0x840, index)
    return buf


def globalb():
    return (chunk(mod.TYPE_TAG, b"\0" * 8 + b"".join(car_record(f"STOCK{i}", i) for i in range(46)))
            + chunk(mod.SKIN_TAG, b"\0" * mod.SKIN)
            + chunk(mod.PART_TAG, b"synthetic placeholder"))


class NativePreviewTests(unittest.TestCase):
    def test_assign_new_index_and_reindex_skin(self):
        base = globalb()
        record = car_record("CIVICEK9", 56)
        record[0x880] = 1
        skin = struct.pack("<II", 56, 1) + bytes(mod.SKIN - 8)
        part = b"CIVICEK9\0" + struct.pack("<I", 270)
        report, actual, skins = mod.native_plan(base, "CIVICEK9", bytes(record) + skin, part)
        self.assertEqual(report["source_index"], 56)
        self.assertEqual(report["proposed_index"], 46)
        self.assertEqual(report["proposed_type_count"], 47)
        self.assertEqual(report["exported_part_count"], 270)
        self.assertEqual(mod.u32(actual, 0x840), 46)
        self.assertEqual(mod.u32(skins, 0), 46)
        self.assertEqual(mod.u32(record, 0x840), 56)
        self.assertEqual(base, globalb())
        self.assertFalse(report["playable"])

    def test_reject_duplicate_and_skin_mismatch(self):
        record = car_record("STOCK0", 56)
        with self.assertRaisesRegex(ValueError, "collides"):
            mod.native_plan(globalb(), "STOCK0", record, b"STOCK0\0" + struct.pack("<I", 1))
        record = car_record("TESTCAR", 56)
        skin = struct.pack("<II", 55, 1) + bytes(mod.SKIN - 8)
        with self.assertRaisesRegex(ValueError, "skin car index"):
            mod.native_plan(globalb(), "TESTCAR", bytes(record) + skin, b"TESTCAR\0" + struct.pack("<I", 1))

    def test_reject_wrong_baseline_and_invalid_chunk(self):
        record = car_record("TESTCAR", 56)
        with self.assertRaisesRegex(ValueError, "expected 46"):
            mod.native_plan(chunk(mod.TYPE_TAG, b"\0" * 8 + bytes(record)), "TESTCAR", record, b"")
        with self.assertRaisesRegex(ValueError, "truncated"):
            list(mod.top_chunks(struct.pack("<II", 1, 200) + b"x"))


if __name__ == "__main__":
    unittest.main()
