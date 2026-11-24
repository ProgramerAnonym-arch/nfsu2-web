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
from packcheck import jdlz_native
from vinylpacks import jdlz_pack
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


def pack_globalb(data):
    """Use the established game-compatible encoder and strict runtime verifier."""
    packed=jdlz_pack(data)
    decoded,why=jdlz_native(packed)
    if why or decoded!=data or native.jdlz(packed)!=data:
        raise ValueError(f"GLOBALB runtime decompression verification failed: {why}")
    if len(packed)>=len(data):
        raise ValueError("GLOBALB compression did not reduce the bundle")
    return packed


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



def stock_folder_refs(data, car):
    """Conservative scan of the original CarTypeInfo identity/path fields.

    This is not proof that no other game resource uses a folder. A folder
    unused by the original type records may be staged only in the isolated
    preview, never overwritten in the retail installation.
    """
    b,e=native.unique_chunk(data,native.TYPE_TAG)
    start=b+(-b)%16
    if e-start != 46*native.TYPE:
        raise ValueError("folder audit requires the 46 original type records")
    refs=[]
    wanted=car.upper()
    for at in range(start,e,native.TYPE):
        row=data[at:at+native.TYPE]
        name=native.name_at(row,0,32)
        fields=[row[i:i+32].split(b"\0",1)[0].decode("ascii","replace").upper().replace("\\","/")
                for i in range(0,0xc0,32)]
        if wanted in fields[:2] or any(wanted in field.split("/") for field in fields[2:]):
            refs.append(name)
    return refs


def folder_audit(game, base, cars):
    folder=native.child(game,"CARS")
    entries={}
    for item in folder.iterdir():
        entries.setdefault(item.name.upper(),[]).append(item)
    report={}
    for car in cars:
        refs=stock_folder_refs(base,car)
        existing=entries.get(car,[])
        if len(existing)>1:
            raise ValueError(f"ambiguous case-insensitive car folder: {car}")
        if existing and not existing[0].is_dir():
            raise ValueError(f"non-directory collision: {car}")
        report[car]={"original_folder":str(existing[0]) if existing else None,
                     "stock_type_refs":refs,
                     "status":"stock_reference_conflict" if refs else
                         ("existing_folder_no_stock_type_reference" if existing else "new_folder"),
                     "original_files":[]}
        if existing:
            report[car]["original_files"]=[{"name":p.name,"bytes":p.stat().st_size}
                for p in sorted(existing[0].iterdir()) if p.is_file()]
    return report


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
    packed=pack_globalb(combined)
    if native.jdlz(packed)!=combined:
        raise ValueError("GLOBALB compression roundtrip failed")
    assets={"GLOBAL/GLOBALB.LZC":packed,"SPEED2.EXE":executable}
    cars=[r["car"] for r in manifest["vehicles"] if r["status"]=="native_type_and_skin_preview"]
    collisions=folder_audit(game,base,cars)
    for car,info in collisions.items():
        if info["status"]!="new_folder":
            print("FOLDER AUDIT:",car,json.dumps(info,ensure_ascii=False))
    conflicts={car:info["stock_type_refs"] for car,info in collisions.items() if info["stock_type_refs"]}
    if conflicts:
        raise ValueError(f"active original type/path conflicts: {conflicts}; separate asset mapping required")
    for row in manifest["vehicles"]:
        if row["status"]!="native_type_and_skin_preview":
            continue
        car=row["car"]
        if not re.fullmatch(r"[A-Z0-9_]{1,31}",car):
            raise ValueError("invalid staged vehicle name")
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
            "folder_audit":collisions,
            "folder_audit_limit":"Existing folders without stock CarTypeInfo references are staged only. Other resource references must be checked before activating the overlay.",
            "files":[{"path":name,"bytes":len(data),"sha256":sha(data)} for name,data in sorted(assets.items())],
            "remaining":["stock-list builder, quantizers and car-lot/garage/save logic",
                         "collision volumes, sound mappings and frontend names/logos",
                         "verify all resource references for preexisting car folders before activation",
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
