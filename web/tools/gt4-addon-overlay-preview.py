#!/usr/bin/env python3
"""Assemble a private experimental overlay from verified native chunks.

No game files, generated WASM, or saves are modified. This is not a playable
installation. Keep the original installation and executable separate.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location("database",HERE/"gt4-addon-database-preview.py")
db=importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)
native=db.native
ALIGN=2048
TYPE_NAMES={native.TYPE_TAG:"CarTypeInfo.chunk",native.SKIN_TAG:"SkinInfo.chunk",
            native.PART_TAG:"DBModelParts.chunk"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def assemble(base, replacements):
    if replacements.keys()!=TYPE_NAMES.keys():
        raise ValueError("expected exactly three replacement chunks")
    out=bytearray()
    original_other=[]
    for tag,b,e in native.top_chunks(base):
        start=b-8
        if tag in replacements:
            incoming=replacements[tag]
            if len(incoming)<8 or struct.unpack_from("<II",incoming)!=(tag,len(incoming)-8):
                raise ValueError(f"invalid replacement chunk {tag:#x}")
            # Preserve absolute alignment of the first record/subchunk and
            # keep every untouched chunk at its original offset modulo 2048.
            payload=incoming
        else:
            payload=base[start:e]
            original_other.append(payload)
        delta=(start-len(out))%ALIGN
        if delta:
            if delta<8:
                delta+=ALIGN
            out.extend(db.block(0,bytes(delta-8)))
        if len(out)%ALIGN!=start%ALIGN:
            raise ValueError("failed to preserve top-level alignment")
        out.extend(payload)
    # Check every original non-target chunk byte for byte, in order; new
    # null padding blocks are ignored during this comparison.
    actual=[bytes(out[b-8:e]) for tag,b,e in native.top_chunks(out) if tag not in replacements and tag!=0]
    expected=[c for c in original_other if native.u32(c,0)!=0]
    if actual!=expected:
        raise ValueError("an unrelated GLOBALB chunk changed")
    for tag,expected_chunk in replacements.items():
        b,e=native.unique_chunk(out,tag)
        if out[b-8:e]!=expected_chunk:
            raise ValueError("assembled target chunk changed")
    return bytes(out)


def literal_jdlz(data):
    # JDLZ literal-only encoding. The second flag byte is consumed once
    # because there are no back references. Avoid expensive recompression.
    payload=bytearray()
    for at in range(0,len(data),8):
        payload.append(0)
        if at==0:
            payload.append(0)
        payload.extend(data[at:at+8])
    return struct.pack("<4sIII",b"JDLZ",0x1002,len(data),16+len(payload))+payload


def audit_stock(data):
    b,e=native.unique_chunk(data,native.TYPE_TAG)
    start=b+(-b)%16
    if e<start or (e-start)%native.TYPE:
        raise ValueError("assembled car records misaligned")
    eligible=[]
    all_names=[]
    for i,at in enumerate(range(start,e,native.TYPE)):
        r=data[at:at+native.TYPE]
        name=native.name_at(r,0,32)
        if native.u32(r,0x840)!=i:
            raise ValueError("nonsequential assembled vehicle index")
        all_names.append(name)
        # Stock list eligibility documented by Unlimiter FeCarLimits.h:
        # geometry filename, Underground 2 flag, racer usage.
        if r[0x40] and r[0xda]&2 and native.u32(r,0x844)==0:
            eligible.append(name)
    if len(set(all_names))!=len(all_names):
        raise ValueError("duplicate assembled vehicle names")
    return {"types":len(all_names),"eligible_stock_count":len(eligible),
            "stock_capacity":48,"fits_stock_array_by_filter":len(eligible)<=48,
            "eligible_stock_names":eligible,
            "note":"Static eligibility only; original builder and career unlock logic must still be verified."}


def build(game,batch,database,runtime):
    manifest=json.loads((batch/"report.json").read_text())
    dbreport=json.loads((database/"report.json").read_text())
    rt=json.loads((runtime/"report.json").read_text())
    base_path=native.child(native.child(game,"GLOBAL"),"GLOBALB.LZC")
    base=native.load_global(base_path)
    if sha(base)!=dbreport["base_globalb_sha256"]:
        raise ValueError("original GLOBALB differs from database preview")
    if rt["status"]!="experimental_lift_input_only" or not all(r["matches"] for r in rt["patches"]) or len(rt["patches"])!=15:
        raise ValueError("runtime patch preview is not verified")
    if rt["types"]!=dbreport["types"] or rt["parts"]!=dbreport["new_parts"]:
        raise ValueError("runtime/database count mismatch")
    executable=(runtime/"SPEED2.EXE").read_bytes()
    if sha(executable)!=rt["patched_sha256"]:
        raise ValueError("runtime preview executable hash mismatch")
    if sha(native.child(game,"SPEED2.EXE").read_bytes())!=rt["original_sha256"]:
        raise ValueError("original executable differs from runtime preview baseline")
    # Rebuild the chunks from the verified staged exports; do not trust
    # the on-disk preview just because its report exists.
    rebuilt,stats=db.build(game,batch)
    for name,data in rebuilt.items():
        if (database/name).read_bytes()!=data:
            raise ValueError(f"database chunk differs from rebuilt source: {name}")
    if stats!=dbreport:
        raise ValueError("database report differs from rebuilt source")
    combined=assemble(base,{tag:rebuilt[name] for tag,name in TYPE_NAMES.items()})
    stock=audit_stock(combined)
    if stock["types"]!=rt["types"]:
        raise ValueError("assembled type count differs from runtime")
    packed=literal_jdlz(combined)
    if native.jdlz(packed)!=combined:
        raise ValueError("GLOBALB compression roundtrip failed")
    assets={"GLOBAL/GLOBALB.LZC":packed,"SPEED2.EXE":executable}
    for row in manifest["vehicles"]:
        if row["status"]!="native_type_and_skin_preview":
            continue
        car=row["car"]
        if not re.fullmatch(r"[A-Z0-9_]{1,31}",car):
            raise ValueError("invalid staged vehicle name")
        folder=native.child(game,"CARS")
        if any(p.name.casefold()==car.casefold() for p in folder.iterdir()):
            raise ValueError(f"addon folder would collide with original: {car}")
        prefix=f"CARS/{car}/"
        for f in row["files"]:
            name=f["path"]
            if not name.startswith(prefix):
                continue
            if name[len(prefix):] not in ("GEOMETRY.BIN","TEXTURES.BIN","VINYLS.BIN","PARTS_ANIMATIONS.BIN"):
                raise ValueError("unexpected car asset path")
            path=batch/car/name
            if path.stat().st_size!=f["bytes"] or not 0<f["bytes"]<=256*1024*1024:
                raise ValueError("staged asset size mismatch")
            data=path.read_bytes()
            if sha(data)!=f["sha256"]:
                raise ValueError(f"staged asset hash mismatch: {name}")
            assets[name]=data
        for required in ("GEOMETRY.BIN","TEXTURES.BIN"):
            if prefix+required not in assets:
                raise ValueError(f"missing required asset {car}/{required}")
    report={"status":"isolated_overlay_only","playable":False,
            "types":stock["types"],"parts":stats["new_parts"],"stock_list_audit":stock,
            "globalb_unpacked_bytes":len(combined),"globalb_packed_bytes":len(packed),
            "globalb_sha256":sha(combined),
            "files":[{"path":name,"bytes":len(data),"sha256":sha(data)} for name,data in sorted(assets.items())],
            "remaining":["stock-list builder, quantizers and car-lot/garage/save logic",
                         "collision volumes, sound mappings and frontend names/logos",
                         "isolated lift/build and gameplay tests"]}
    return assets,report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch",required=True,type=Path)
    p.add_argument("--database",required=True,type=Path)
    p.add_argument("--runtime",required=True,type=Path)
    p.add_argument("--game",default=ROOT/".nfsu2-local"/"game",type=Path)
    a=p.parse_args()
    try:
        assets,report=build(a.game,a.batch,a.database,a.runtime)
        parent=ROOT/".nfsu2-local"/"overlay-previews"
        parent.mkdir(parents=True,exist_ok=True)
        output=Path(tempfile.mkdtemp(prefix="overlay-",dir=parent))
        for name,data in assets.items():
            target=output/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        (output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps({k:v for k,v in report.items() if k!="files"},indent=2))
        print("Overlay files:",len(assets))
        print("Preview:",output)
        print("NOT INSTALLED: do not use this overlay as the live game directory.")
    except (OSError,ValueError,KeyError,IndexError,struct.error) as e:
        p.exit(1,f"Overlay preview rejected: {e}\n")


if __name__=="__main__":
    main()
