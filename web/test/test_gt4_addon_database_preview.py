"""Asset-free native DBModelParts append tests."""
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

tools=Path(__file__).resolve().parents[1]/"tools"
sys.path.insert(0,str(tools))
spec=importlib.util.spec_from_file_location("db",tools/"gt4-addon-database-preview.py")
db=importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)


def original():
    hdr=bytearray(0x3c)
    struct.pack_into("<I",hdr,8,6)
    for off,count in ((0x20,1),(0x28,1),(0x30,0),(0x38,1)):
        struct.pack_into("<I",hdr,off,count)
    return b"".join(db.block(tag,body) for tag,body in (
        (db.HDR,hdr),(db.STR,b"\0"*8+b"OLD\0"),(db.LIST,struct.pack("<HH",1,0)),
        (db.ATTR,struct.pack("<II",db.hash_name("STOCK"),1)),
        (db.MODEL,b""),(db.OWNER,struct.pack("<I",db.hash_name("OLD"))),
        (db.PART,struct.pack("<IBHBHHH",db.hash_name("OLD_BODY"),5,0,0,2,0,0xffff))))


def collection(name="NEW"):
    return {"car":name,"parts":[{"label":"NEW_BODY","debug_name":"BODY","group":5,"upgrade_group":0,
            "lod":{"templated":True,"concatenator":"NEW","geometry":["BODY_A"]+[None]*7},
            "attributes":[{"key":db.hash_name("STOCK"),"name":"STOCK","type":1,"custom":False,"value":True}]}]}


class NativeDBTest(unittest.TestCase):
    def test_appends_and_preserves_prefix(self):
        base=original()
        merged,stats=db.merge_parts(base,[collection()])
        self.assertEqual(stats["new_parts"],2)
        self.assertEqual(stats["new_owners"],2)
        self.assertEqual(stats["new_attributes"],1)
        self.assertEqual(stats["new_models"],1)
        self.assertEqual(merged[:4],struct.pack("<I",db.native.PART_TAG))
        old={tag:base[b:e] for tag,b,e in db.native.top_chunks(base)}
        body=merged[8:]
        new={tag:body[b:e] for tag,b,e in db.native.top_chunks(body)}
        for tag in (db.STR,db.LIST,db.ATTR,db.OWNER,db.PART):
            self.assertTrue(new[tag].startswith(old[tag]))
        self.assertEqual(struct.unpack_from("<IBHBHHH",new[db.PART],14)[3],1)
        self.assertEqual(base,original())

    def test_reject_existing_owner(self):
        with self.assertRaisesRegex(ValueError,"owner already exists"):
            db.merge_parts(original(),[collection("OLD")])

    def test_reject_capacity_and_invalid_header(self):
        with self.assertRaises(ValueError):
            db.checked16(65535)
        bad=bytearray(original())
        struct.pack_into("<I",bad,16,5)
        with self.assertRaisesRegex(ValueError,"header"):
            db.merge_parts(bytes(bad),[collection()])


if __name__=="__main__":
    unittest.main()
