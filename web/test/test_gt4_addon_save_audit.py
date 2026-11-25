import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location("audit",Path(__file__).resolve().parents[1]/"tools"/"gt4-addon-save-audit.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def profile(key):
    f=bytearray(54966)
    f[:4]=b"20CM"
    struct.pack_into("<III",f,4,54966,8,54930)
    struct.pack_into("<II",f,28,0x10d,54930)
    f[36+53761:36+53761+3]=b"GT4"
    at=36+22596
    struct.pack_into("<I",f,at+4,123)
    struct.pack_into("<II",f,at+28,mod.native.hash_name("CIVICEK9"),key)
    f[at+1073]=1
    mod.saves.seal(f)
    return bytes(f)


class SaveAuditTest(unittest.TestCase):
    def test_checksum_failure(self):
        f=bytearray(profile(1234))
        mod.validate_profile(f)
        f[-1]^=1
        with self.assertRaises(ValueError):
            mod.validate_profile(f)

    def test_roundtrip_and_changed_part(self):
        cars=[{"hash":f"{mod.native.hash_name('CIVICEK9'):08x}","id":"CIVICEK9"}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"save.zip"
            with zipfile.ZipFile(p,"w") as z:
                z.writestr("NFS Underground 2/GT4/GT4",profile(1234))
            a=mod.snapshot(p,cars,{1234})
            self.assertEqual(a[0]["records"][0]["type"],"CIVICEK9")
            self.assertEqual(a[0]["records"][0]["unresolved_part_slots"],[])
            self.assertTrue(mod.compare(a,a)[0]["same_part_keys"])
            with zipfile.ZipFile(p,"w") as z:
                z.writestr("NFS Underground 2/GT4/GT4",profile(5678))
            b=mod.snapshot(p,cars,{1234,5678})
            r=mod.compare(a,b)[0]
            self.assertTrue(r["same_type"])
            self.assertFalse(r["same_part_keys"])
            self.assertEqual(r["changed_slots"],["00"])


if __name__=="__main__":
    unittest.main()
