#!/usr/bin/env python3
"""Experimental lift-input patch for native addon database bounds.

Only the verified NA v1.2 executable is accepted. The original remains
unchanged. The private output is NOT a playable build; frontend stock lists,
career, quantizer initialization, sound and runtime hooks need verification.
Addresses cross-checked against NFSU2Unlimiter Game.h (LoaderCarInfo_Hook).
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[2]
STOCK_SHA = "f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7"
BASE_SHA = "07e1c37a2e5ba4b3e6a17b257e653409c31d5f0b3f9df3464aec36adbbced9d0"
TYPE_SIZE = 0x890
TYPE_SITES = (0x41AB83,0x5165BC,0x5207B3,0x609348,0x6099B1,0x636C24)
COUNT_SITES = (0x5596CB,0x5EFC5A,0x610150,0x61C671,0x6372B4,0x513D1D)
PART_SITES = (0x5EFC43,0x5F04A4,0x5F0675)


def plan(types, parts):
    if not 46 < types <= 63 or not 12167 < parts <= 16383:
        raise ValueError("preview restricted to original quantizer bit widths")
    return ([(a,4,46*TYPE_SIZE,types*TYPE_SIZE,"type table byte size") for a in TYPE_SITES]
          + [(a,1,46,types,"type count") for a in COUNT_SITES]
          + [(a,4,12167+(a==PART_SITES[-1]),parts+(a==PART_SITES[-1]),"part count") for a in PART_SITES])


def patch_bytes(data, pe, sites):
    """Resolve virtual addresses in executable sections and verify all old bytes."""
    result=bytearray(data)
    audit=[]
    if pe.OPTIONAL_HEADER.ImageBase != 0x400000 or pe.FILE_HEADER.Machine != 0x14c:
        raise ValueError("expected original x86 PE at image base 0x400000")
    for va,width,old,new,label in sites:
        rva=va-pe.OPTIONAL_HEADER.ImageBase
        section=pe.get_section_by_rva(rva)
        if section is None or not section.Characteristics & 0x20000000:
            raise ValueError(f"{va:#x}: not an executable section")
        offset=pe.get_offset_from_rva(rva)
        if offset<0 or offset+width>len(data):
            raise ValueError(f"{va:#x}: invalid file offset")
        actual=int.from_bytes(data[offset:offset+width],"little")
        audit.append({"va":hex(va),"offset":hex(offset),"width":width,"expected":old,
                      "actual":actual,"new":new,"label":label,"matches":actual==old})
        if actual==old:
            result[offset:offset+width]=new.to_bytes(width,"little")
    return bytes(result),audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True,type=Path)
    p.add_argument("--game",type=Path,default=ROOT/".nfsu2-local"/"game")
    p.add_argument("--write-preview",action="store_true")
    a=p.parse_args()
    try:
        import pefile
        report=json.loads((a.database/"report.json").read_text())
        if report["status"]!="offline_native_chunks_only" or report["base_globalb_sha256"]!=BASE_SHA:
            raise ValueError("unexpected database preview or baseline")
        types,parts=report["types"],report["new_parts"]
        if report["original_parts"]!=12167:
            raise ValueError("unexpected original part count")
        matches=[f for f in a.game.iterdir() if f.name.upper()=="SPEED2.EXE" and f.is_file()]
        if len(matches)!=1:
            raise ValueError("expected exactly one original SPEED2.EXE")
        original=matches[0].read_bytes()
        if hashlib.sha256(original).hexdigest()!=STOCK_SHA:
            raise ValueError("executable SHA256 differs from verified NA v1.2 baseline")
        pe=pefile.PE(data=original,fast_load=True)
        patched,audit=patch_bytes(original,pe,plan(types,parts))
        for row in audit:
            print(f"{row['va']} {row['label']}: {row['actual']} -> {row['new']} "
                  + ("OK" if row["matches"] else f"MISMATCH (expected {row['expected']})"))
        if not all(r["matches"] for r in audit):
            raise ValueError("one or more original immediates differed; no output written")
        result={"status":"experimental_lift_input_only","playable":False,
                "types":types,"parts":parts,"original_sha256":STOCK_SHA,
                "patched_sha256":hashlib.sha256(patched).hexdigest(),"patches":audit,
                "remaining":["runtime fixed stock-list and save guards",
                             "quantizer runtime values and other car-specific arrays",
                             "aligned GLOBALB assembly and collision/sound/label resources",
                             "actual WASM compilation and gameplay"]}
        if a.write_preview:
            parent=ROOT/".nfsu2-local"/"runtime-previews"
            parent.mkdir(parents=True,exist_ok=True)
            output=Path(tempfile.mkdtemp(prefix="lift-",dir=parent))
            (output/"SPEED2.EXE").write_bytes(patched)
            (output/"report.json").write_text(json.dumps(result,indent=2)+"\n")
            print("Preview:",output)
        print("Verified patch sites:",len(audit))
        print("NOT INSTALLED: do not launch or lift this preview yet.")
    except (OSError,ValueError,KeyError,ImportError,struct.error) as e:
        p.exit(1,f"Runtime preview rejected: {e}\n")


if __name__=="__main__":
    main()
