#!/usr/bin/env python3
"""Read-only GT4 catalog and save evidence from the actual native database.

Use the experimental game directory and optional browser backup ZIP(s).
Never modifies the game, profiles, or original installation. A backup
comparison proves stored identifiers/part keys, not visual behavior.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import struct
import sys
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import addoncar_seed as saves
spec=importlib.util.spec_from_file_location("native",HERE/"gt4-addon-native-preview.py")
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

ADDONS=("CIVICEK9","CIVICEG","CORVETTEC5","INFIFX45","GS300","IMPREZA",
        "INTEGRA","LANCER","NEONC","NSX","S2000","CHARGER")
NONE={0,0xffffffff}


def catalog(raw):
    b,e=native.unique_chunk(raw,native.TYPE_TAG)
    start=b+(-b)%16
    if (e-start)%native.TYPE or (e-start)//native.TYPE not in (46,58):
        raise ValueError("unexpected vehicle table")
    cars=[]
    for i,at in enumerate(range(start,e,native.TYPE)):
        r=raw[at:at+native.TYPE]
        name=native.name_at(r,0,32)
        h=native.u32(r,0xd0)
        if native.u32(r,0x840)!=i or h!=native.hash_name(name):
            raise ValueError(f"invalid type record {i}")
        cars.append({"id":name,"index":i,"hash":f"{h:08x}",
                     "manufacturer":native.name_at(r,0xc0,16),
                     "game_price":native.u32(r,0x87c),
                     "eligible":bool(r[0x40] and r[0xda]&2 and native.u32(r,0x844)==0),
                     "physics_sha256":hashlib.sha256(r[0x110:0x720]).hexdigest(),
                     "addon":i>=46})
    if len(cars)==58 and tuple(c["id"] for c in cars[46:])!=ADDONS:
        raise ValueError("unexpected addon order")
    b,e=native.unique_chunk(raw,native.PART_TAG)
    blocks={t:raw[b+x:b+y] for t,x,y in native.top_chunks(raw[b:e])}
    count=native.u32(blocks[0x34603],0x38)
    parts=blocks[0x34604]
    if len(parts)<14*count:
        raise ValueError("truncated native part records")
    keys={native.u32(parts,14*i) for i in range(count)}
    return cars,keys,count


def validate_profile(data):
    if len(data)!=54966 or data[:4]!=b"20CM":
        raise ValueError("not a NA v1.2 profile")
    if struct.unpack_from("<III",data,4)!=(54966,8,54930) or struct.unpack_from("<II",data,28)!=(0x10d,54930):
        raise ValueError("unexpected profile header")
    if struct.unpack_from("<III",data,16)!=(saves.checksum(data[28:36]),saves.checksum(data[36:]),saves.checksum(data[:24])):
        raise ValueError("profile checksums do not match")
    return data[36:]


def read_zip(path):
    # Read only profiles and sidecars; never extract or inspect screenshots.
    found={}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            p=PurePosixPath(info.filename.replace("\\","/"))
            if p.is_absolute() or ".." in p.parts:
                raise ValueError("unsafe backup member path")
            if info.file_size==54966 or (p.name.upper()=="GARAGE.DAT" and info.file_size==10202):
                key=str(p).casefold()
                if key in found:
                    raise ValueError("duplicate backup member")
                if len(found)>=1000:
                    raise ValueError("too many candidate backup members")
                found[key]=z.read(info)
    return found


def snapshot(path,cars,keys):
    byhash={int(c["hash"],16):c["id"] for c in cars}
    files=read_zip(path) if zipfile.is_zipfile(path) else {path.name.casefold():path.read_bytes()}
    profiles=[]
    for name,data in files.items():
        if not data.startswith(b"20CM"):
            continue
        pl=validate_profile(data)
        profile=pl[53761:53793].split(b"\0",1)[0].decode("ascii","replace")
        rows=[]
        def row(label,rec):
            h=native.u32(rec,28)
            if h in NONE:
                return
            slots=struct.unpack_from("<170I",rec,32)
            rows.append({"record":label,"handle":f"{native.u32(rec,4):08x}",
                         "type":byhash.get(h,f"unknown:{h:08x}"),
                         "part_keys":{f"{i:02x}":f"{k:08x}" for i,k in enumerate(slots) if k not in NONE},
                         "unresolved_part_slots":[f"{i:02x}" for i,k in enumerate(slots) if k not in NONE and k not in keys]})
        for i in range(20):
            at=1156+i*1072
            # Nonzero type records include retained/unused customized slots.
            row(f"customize:{i+1}",pl[at:at+1072])
        for i in range(5):
            at=22596+i*2034
            rec=pl[at:at+2034]
            if rec[1073]:
                row(f"career:{i+1}",rec)
        for i in range(6):
            at=32770+i*1076
            row(f"preset:{i+1}",pl[at:at+1076])
        garage=files.get(str(PurePosixPath(name).parent/"garage.dat"))
        garage_valid=None
        if garage is not None:
            garage_valid=(len(garage)==10202 and struct.unpack_from("<II",garage)==(0x4147324e,1)
                          and struct.unpack_from("<Q",garage,8)[0]==saves.fnv64(pl[:39230]))
            if garage_valid:
                for i in range(5):
                    rec=garage[32+i*2034:32+(i+1)*2034]
                    if rec[1073]:
                        row(f"career:{i+6}",rec)
        profiles.append({"profile":profile,"checksums_valid":True,"garage_fingerprint_valid":garage_valid,
                         "records":rows})
    if not profiles:
        raise ValueError("no supported profile found in backup")
    return profiles


def compare(before,after):
    def flatten(profiles):
        return {(p["profile"],r["record"]):r for p in profiles for r in p["records"]}
    a,b=flatten(before),flatten(after)
    result=[]
    for k,r in a.items():
        if r["type"] not in ADDONS:
            continue
        now=b.get(k)
        result.append({"profile":k[0],"record":k[1],"type":r["type"],
                       "same_handle":bool(now and now["handle"]==r["handle"]),
                       "same_type":bool(now and now["type"]==r["type"]),
                       "same_part_keys":bool(now and now["part_keys"]==r["part_keys"]),
                       "changed_slots":sorted(s for s in set(r["part_keys"])|set(now["part_keys"] if now else {})
                           if r["part_keys"].get(s)!=(now["part_keys"].get(s) if now else None))})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game",required=True,type=Path)
    p.add_argument("--before",type=Path)
    p.add_argument("--after",type=Path)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    try:
        if a.after and not a.before:
            raise ValueError("--after requires --before")
        raw=native.load_global(native.child(native.child(a.game,"GLOBAL"),"GLOBALB.LZC"))
        cars,keys,n=catalog(raw)
        report={"status":"read_only_audit","native_part_count":n,
                "eligible_count":sum(c["eligible"] for c in cars),
                "catalog":cars,"notes":["game prices are not verified dealership prices",
                  "physics hashes are not real-world technical specifications",
                  "unresolved part keys may be sidecar-managed; not alone proof of corruption",
                  "customize and preset records may be unused; physical tests remain required"]}
        if a.before:
            report["before"]=snapshot(a.before,cars,keys)
        if a.after:
            report["after"]=snapshot(a.after,cars,keys)
            report["addon_roundtrip"]=compare(report["before"],report["after"])
        result=json.dumps(report,indent=2,ensure_ascii=False)
        if a.output:
            # Exclusive create only: cannot overwrite existing game/save files.
            with a.output.open("x",encoding="utf-8") as f:
                f.write(result+"\n")
        else:
            print(result)
        print(f"Catalog: {len(cars)} types, {report['eligible_count']} eligible, {n} native parts")
        if "addon_roundtrip" in report:
            rows=report["addon_roundtrip"]
            print("Addon roundtrip:",len(rows),"candidate records;",
                  sum(r["same_handle"] and r["same_type"] and r["same_part_keys"] for r in rows),"unchanged")
        print("READ ONLY: no game files or profiles modified.")
    except (OSError,ValueError,KeyError,struct.error,zipfile.BadZipFile) as e:
        p.exit(1,f"Audit rejected: {e}\n")


if __name__=="__main__":
    main()
