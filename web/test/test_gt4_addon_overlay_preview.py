"""Offline overlay alignment and compression regression tests."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import sys
import unittest

tools=Path(__file__).resolve().parents[1]/"tools"
sys.path.insert(0,str(tools))
spec=importlib.util.spec_from_file_location("overlay",tools/"gt4-addon-overlay-preview.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class OverlayTest(unittest.TestCase):
    def test_preserves_non_target_chunks_and_alignment(self):
        block=mod.db.block
        original=block(0x1234,b"unchanged")+b"".join(
            block(tag,b"x"*16)+block(0x1235+i,bytes([i])*37)
            for i,tag in enumerate(mod.TYPE_NAMES))
        replacements={tag:block(tag,b"y"*(16+i*7+1)) for i,tag in enumerate(mod.TYPE_NAMES)}
        actual=mod.assemble(original,replacements)
        before={tag:(b%mod.ALIGN,original[b:e]) for tag,b,e in mod.native.top_chunks(original)}
        after={tag:(b%mod.ALIGN,actual[b:e]) for tag,b,e in mod.native.top_chunks(actual) if tag!=0}
        for tag,(offset,data) in before.items():
            self.assertEqual(after[tag][0],offset)
            self.assertEqual(after[tag][1],replacements[tag][8:] if tag in replacements else data)

    def test_runtime_compatible_jdlz_roundtrip(self):
        for n in (128,256,2048,2049,8192):
            data=(b"GLOBALB\0"* ((n+7)//8))[:n]
            packed=mod.pack_globalb(data)
            self.assertEqual(mod.native.jdlz(packed),data)
            self.assertEqual(mod.jdlz_native(packed),(data,None))
            self.assertLess(len(packed),len(data))


    def test_stock_filter(self):
        records=[]
        for i,(flag,usage) in enumerate(((2,0),(0,0),(2,1))):
            row=bytearray(mod.native.TYPE)
            row[:2]=f"C{i}".encode()
            row[0x40]=ord("G")
            row[0xda]=flag
            struct.pack_into("<II",row,0x840,i,usage)
            records.append(row)
        data=mod.db.block(mod.native.TYPE_TAG,b"\0"*8+b"".join(records))
        audit=mod.audit_stock(data)
        self.assertEqual(audit["types"],3)
        self.assertEqual(audit["eligible_stock_names"],["C0"])



    def test_folder_audit_distinguishes_exact_path_components(self):
        records=[]
        for i in range(46):
            row=bytearray(mod.native.TYPE)
            name=("IMPREZAWRX" if i==0 else f"STOCK{i}").encode()
            row[:len(name)]=name
            if i==0:
                geometry=b"CARS\\IMPREZAWRX\\GEOMETRY.BIN"
                row[0x40:0x40+len(geometry)]=geometry
            if i==1:
                geometry=b"CARS\\SHARED\\GEOMETRY.BIN"
                row[0x40:0x40+len(geometry)]=geometry
            struct.pack_into("<I",row,0x840,i)
            records.append(row)
        base=mod.db.block(mod.native.TYPE_TAG,b"\0"*8+b"".join(records))
        self.assertEqual(mod.stock_folder_refs(base,"IMPREZA"),[])
        self.assertEqual(mod.stock_folder_refs(base,"IMPREZAWRX"),["IMPREZAWRX"])
        self.assertEqual(mod.stock_folder_refs(base,"SHARED"),["STOCK1"])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"CARS"/"IMPREZA").mkdir(parents=True)
            (root/"CARS"/"IMPREZA"/"GEOMETRY.BIN").write_bytes(b"original")
            audit=mod.folder_audit(root,base,["IMPREZA","SHARED","NEWCAR"])
            self.assertEqual(audit["IMPREZA"]["status"],"existing_folder_no_stock_type_reference")
            self.assertEqual(audit["SHARED"]["status"],"stock_reference_conflict")
            self.assertEqual(audit["NEWCAR"]["status"],"new_folder")
            self.assertEqual((root/"CARS"/"IMPREZA"/"GEOMETRY.BIN").read_bytes(),b"original")


if __name__=="__main__":
    unittest.main()
