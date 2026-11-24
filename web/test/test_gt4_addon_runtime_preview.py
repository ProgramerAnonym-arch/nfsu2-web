"""Synthetic tests for the isolated car bounds patch preview."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location("bounds",Path(__file__).resolve().parents[1]/"tools"/"gt4-addon-runtime-preview.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakePE:
    OPTIONAL_HEADER=SimpleNamespace(ImageBase=0x400000)
    FILE_HEADER=SimpleNamespace(Machine=0x14c)
    def get_section_by_rva(self,rva):
        return SimpleNamespace(Characteristics=0x20000000)
    def get_offset_from_rva(self,rva):
        return rva


class BoundsTest(unittest.TestCase):
    def test_plan(self):
        sites=mod.plan(58,14557)
        self.assertEqual(len(sites),15)
        self.assertEqual(sites[0][3],58*0x890)
        self.assertEqual(sites[-1][3],14558)
        self.assertEqual(len({r[0] for r in sites}),len(sites))

    def test_limits(self):
        for types,parts in [(64,14557),(58,16384),(46,14557)]:
            with self.assertRaises(ValueError):
                mod.plan(types,parts)

    def test_bytes_verified_without_mutation(self):
        sites=[(0x400001,1,46,58,"count"),(0x400004,4,12167,14557,"parts")]
        original=b"\0\x2e\0\0"+(12167).to_bytes(4,"little")
        changed,report=mod.patch_bytes(original,FakePE(),sites)
        self.assertEqual(changed[1],58)
        self.assertEqual(int.from_bytes(changed[4:8],"little"),14557)
        self.assertTrue(all(r["matches"] for r in report))
        self.assertEqual(original[1],46)
        _,bad=mod.patch_bytes(changed,FakePE(),sites)
        self.assertFalse(any(r["matches"] for r in bad))


if __name__=="__main__":
    unittest.main()
