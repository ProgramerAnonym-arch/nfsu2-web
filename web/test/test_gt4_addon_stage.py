"""Asset-free regression tests for private addon staging."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

TOOL = Path(__file__).resolve().parents[1] / "tools" / "gt4-addon-stage.py"
spec = importlib.util.spec_from_file_location("addon_stage", TOOL)
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)


def export(raw):
    # A valid literal-only JDLZ stream in a Binary v3 collection envelope.
    payload = bytearray()
    for i in range(0, len(raw), 8):
        payload.append(0)
        if i == 0:
            payload.append(0)
        payload.extend(raw[i:i + 8])
    jdlz = struct.pack("<4sIII", b"JDLZ", 0x1002, len(raw), 16 + len(payload)) + payload
    return struct.pack("<5I", 0x42704D67, 12 + len(jdlz), 3, 0, len(jdlz)) + jdlz


class AddonStageTests(unittest.TestCase):
    def test_literal_export(self):
        raw = b"TESTCAR\0CARS\\TESTCAR\\GEOMETRY.BIN\0"
        self.assertEqual(addon.decode_export(export(raw)), raw)

    def test_corrupt_sizes(self):
        data = bytearray(export(b"TESTCAR\0"))
        struct.pack_into("<I", data, 28, addon.MAX_DB + 1)
        with self.assertRaises(ValueError):
            addon.decode_export(data)

    def test_invalid_back_reference(self):
        payload = bytes([1, 1, 0, 0])
        jdlz = struct.pack("<4sIII", b"JDLZ", 0x1002, 3, 20) + payload
        with self.assertRaises(ValueError):
            addon.decode_export(struct.pack("<5I", 0x42704D67, 12 + len(jdlz), 3, 0, len(jdlz)) + jdlz)

    def make_zip(self, path, identity=b"TESTCAR", duplicate=False):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mod/_setup/TESTCAR/GEOMETRY.BIN", b"fixture geometry")
            z.writestr("mod/_setup/TESTCAR/TEXTURES.BIN", b"fixture textures")
            z.writestr("mod/_setup/CarTypeInfos.bin",
                       export(identity + b"\0CARS\\TESTCAR\\GEOMETRY.BIN\0"))
            z.writestr("mod/_setup/DBModelParts.bin", export(identity + b"\0part"))
            z.writestr("mod/_setup/global_install.end", "not executed")
            z.writestr("../../outside.exe", b"not extracted")
            if duplicate:
                z.writestr("second/TESTCAR/geometry.bin", b"duplicate")

    def test_inspect_selects_only_expected_assets(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.zip"
            self.make_zip(p)
            files = addon.inspect(p, "TESTCAR")
            self.assertEqual(len(files), 6)
            self.assertEqual(files["CARS/TESTCAR/GEOMETRY.BIN"], b"fixture geometry")
            self.assertIn("decoded/CarTypeInfos.bin", files)
            self.assertFalse((Path(d).parent / "outside.exe").exists() and "outside.exe" in files)
            self.assertNotIn("mod/_setup/global_install.end", files)

    def test_rejects_wrong_identity_duplicate_and_invalid_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.zip"
            self.make_zip(p, identity=b"OTHER")
            with self.assertRaises(ValueError):
                addon.inspect(p, "TESTCAR")
            self.make_zip(p, duplicate=True)
            with self.assertRaises(ValueError):
                addon.inspect(p, "TESTCAR")
            with self.assertRaises(ValueError):
                addon.inspect(p, "../TESTCAR")


if __name__ == "__main__":
    unittest.main()
