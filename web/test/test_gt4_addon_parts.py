"""Synthetic tests for complete Binary DBModelParts field decoding."""
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location("parts", Path(__file__).resolve().parents[1] / "tools" / "gt4_addon_parts.py")
parts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parts)


def fixture():
    attributes = (
        struct.pack("<IB", parts.hash_name("STOCK"), 1)
        + struct.pack("<I", parts.hash_name("NAME")) + b"TESTCAR_BODY\0"
        + struct.pack("<I", parts.hash_name("BLEND")) + struct.pack("<I", 0x3f800000)
        + struct.pack("<I", 0x12345678) + b"CUSTOM_STRING\0" + struct.pack("<I", 4) + b"\x01VALUE\0"
    )
    lod = b"\x01\x01\x01BASE\0" + b"\x01" + b"\0"*7 + b"BODY_A\0"
    return (b"TESTCAR\0" + struct.pack("<II", 1, 4) + b"BODY\0DEBUG\0"
            + struct.pack("<BH", 5, 12) + lod + attributes)


class PartsTest(unittest.TestCase):
    def test_fields(self):
        parsed = parts.parse_parts(fixture(), "TESTCAR")
        self.assertEqual(parsed["count"], 1)
        p = parsed["parts"][0]
        self.assertEqual(p["group"], 5)
        self.assertEqual(p["upgrade_group"], 12)
        self.assertEqual(p["lod"]["geometry"], ["BODY_A"] + [None]*7)
        self.assertTrue(p["attributes"][0]["value"])
        self.assertEqual(p["attributes"][1]["value"], "TESTCAR_BODY")
        self.assertEqual(p["attributes"][2]["value"], 0x3f800000)
        self.assertEqual(p["attributes"][3]["value"], "VALUE")

    def test_reject_truncation(self):
        data = fixture()
        for n in range(len(data)):
            with self.subTest(n=n), self.assertRaises(ValueError):
                parts.parse_parts(data[:n], "TESTCAR")

    def test_identity_trailing_bytes(self):
        with self.assertRaises(ValueError):
            parts.parse_parts(fixture(), "OTHER")
        with self.assertRaises(ValueError):
            parts.parse_parts(fixture()+b"x", "TESTCAR")


if __name__ == "__main__":
    unittest.main()
