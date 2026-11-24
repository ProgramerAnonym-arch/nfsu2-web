#!/usr/bin/env python3
"""Build offline native vehicle database chunks from a verified batch.

NOT an installer. Writes separate chunks to ignored private storage only.
The game must not load these before runtime capacity and relocation work.
Native layout reference: Nikki (MIT), Underground2 DBModelPartManager and
CPStruct/attribute serializers. Existing records and references are retained.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import tempfile
from gt4_addon_parts import parse_parts, Reader, hash_name

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("native", HERE/"gt4-addon-native-preview.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
HDR, PART, ATTR, STR, MODEL, OWNER, LIST, CUSTOM = (
    0x34603,0x34604,0x34605,0x34606,0x3460a,0x3460b,0x3460c,0x3460d)
NONE = 0xffffffff


def checked16(n):
    if not 0 <= n < 0xffff:
        raise ValueError(f"native 16-bit reference exceeds capacity: {n}")
    return n


def game_hash(s):
    # Nikki can serialize unresolved hashes as literal hexadecimal keys.
    if re.fullmatch(r"0[xX][0-9a-fA-F]{8}",s):
        return int(s,16)
    return hash_name(s)


def block(tag, body):
    return struct.pack("<II",tag,len(body))+body


def exact_body(data, count, size, label):
    end = count*size
    if end > len(data) or len(data)-end > 15 or any(data[end:]):
        raise ValueError(f"unexpected {label} count/padding")
    return bytearray(data[:end])


def pad_like(data, original):
    return bytes(data)+bytes((len(original)-len(data))%16)


def read_custom(body):
    if not body:
        return {}
    r = Reader(body)
    count = r.number(4)
    if count > 65535:
        raise ValueError("custom attribute count invalid")
    out = {}
    for _ in range(count):
        name, key, kind = r.string(), r.number(4), r.number(4)
        if key in out and out[key][1] != kind:
            raise ValueError("conflicting original custom attribute types")
        out[key] = (name,kind)
    if any(body[r.pos:]):
        raise ValueError("unexpected custom attribute trailer")
    return out


def merge_parts(body, collections):
    original = {}
    for tag,b,e in native.top_chunks(body):
        if tag in original:
            raise ValueError(f"duplicate part subchunk {tag:#x}")
        original[tag]=body[b:e]
    required={HDR,PART,ATTR,STR,MODEL,OWNER,LIST}
    if not required <= original.keys() or original.keys()-required-{CUSTOM}:
        raise ValueError("unsupported original DBModelParts subchunks")
    hdr=bytearray(original[HDR])
    if len(hdr)!=0x3c or native.u32(hdr,8)!=6:
        raise ValueError("unsupported native part header")
    na,no,nm,np=(native.u32(hdr,i) for i in (0x20,0x28,0x30,0x38))
    attrs=exact_body(original[ATTR],na,8,"attribute")
    owners=exact_body(original[OWNER],no,4,"owner")
    models=exact_body(original[MODEL],nm,36,"model")
    parts=exact_body(original[PART],np,14,"part")
    strings=bytearray(original[STR])
    lists=bytearray(original[LIST])
    if len(strings)%4 or len(lists)%2:
        raise ValueError("unaligned original reference buffers")
    custom=read_custom(original.get(CUSTOM,b""))
    aidx={bytes(attrs[i:i+8]):i//8 for i in range(0,len(attrs),8)}
    midx={bytes(models[i:i+36]):i//36 for i in range(0,len(models),36)}
    oidx={native.u32(owners,i):i//4 for i in range(0,len(owners),4)}
    # Discover existing string starts on 4-byte boundaries, only reuse exact
    # contents. Existing bytes are never moved, including padding.
    sidx={}
    for i in range(0,len(strings),4):
        end=strings.find(b"\0",i)
        if end!=-1 and end-i <= 65536:
            sidx.setdefault(bytes(strings[i:end]),i//4)
    lidx={}
    for i in range(0,len(parts),14):
        key,group,upgrade,owner,name,li,mi=struct.unpack_from("<IBHBHHH",parts,i)
        if owner>=no or (name!=0xffff and name*4>=len(strings)) or (mi!=0xffff and mi>=nm):
            raise ValueError("invalid original part references")
        if li!=0xffff:
            start=li*2
            if start+2>len(lists):
                raise ValueError("invalid original attribute list reference")
            count=struct.unpack_from("<H",lists,start)[0]
            stop=start+2+count*2
            if stop>len(lists):
                raise ValueError("invalid original attribute list length")
            if any(x[0]>=na for x in struct.iter_unpack("<H",lists[start+2:stop])):
                raise ValueError("invalid original attribute index")
            lidx[bytes(lists[start:stop])]=li

    def intern(buffer, index, value, width, limit=0xfffe):
        if value not in index:
            pos=len(buffer)//width
            if pos>limit:
                raise ValueError(f"native reference capacity exceeded: {pos}")
            index[value]=pos
            buffer.extend(value)
        return index[value]

    def string_ref(value, limit=0xffffffff-1):
        if value is None:
            return NONE if limit>0xffff else 0xffff
        raw=value.encode("utf-8")
        if b"\0" in raw:
            raise ValueError("embedded null in native string")
        if raw not in sidx:
            sidx[raw]=len(strings)//4
            strings.extend(raw+b"\0"+bytes((-len(raw)-1)%4))
        index=sidx[raw]
        if index>limit:
            raise ValueError("native string reference capacity exceeded")
        return index

    def attr_ref(a):
        key,kind,val=a["key"],a["type"],a["value"]
        if a["custom"]:
            old=custom.get(key)
            if old and old[1]!=kind:
                raise ValueError(f"custom attribute type conflict {key:#x}")
            custom.setdefault(key,(a["name"],kind))
        if kind in (1,2,3):
            value=int(val)
        elif kind==4:
            value=string_ref(val)
        elif kind==5:
            value=string_ref(val[0],0xfffe)|(string_ref(val[1],0xfffe)<<16)
        elif kind==6:
            value=int.from_bytes(val.to_bytes(4,"little")[::-1],"little")
        elif kind==8:
            value=game_hash(val) if val else (hash_name("") if a["custom"] else NONE)
        else:
            raise ValueError("unsupported native attribute")
        return intern(attrs,aidx,struct.pack("<II",key,value),8)

    added={}
    for c in collections:
        name=c["car"]
        owner_hash=game_hash(name)
        if owner_hash in oidx:
            raise ValueError(f"part owner already exists: {name}")
        owner=len(owners)//4
        if owner>255:
            raise ValueError("8-bit part owner capacity exceeded")
        oidx[owner_hash]=owner
        owners.extend(struct.pack("<I",owner_hash))
        for p in c["parts"]:
            debug=string_ref(p["debug_name"],0xfffe)
            refs=[attr_ref(a) for a in p["attributes"]]
            li=0xffff
            if refs:
                encoded=struct.pack("<H",checked16(len(refs)))+b"".join(struct.pack("<H",checked16(x)) for x in refs)
                li=intern(lists,lidx,encoded,2)
            mi=0xffff
            lod=p["lod"]
            if lod is not None:
                if lod["templated"]:
                    base=string_ref(lod["concatenator"],0xfffe)
                    values=[string_ref(v) for v in lod["geometry"]]
                    rec=struct.pack("<HH8I",1,base,*values)
                else:
                    if lod["concatenator"] is not None:
                        raise ValueError("unexpected untemplated concatenator")
                    rec=struct.pack("<HH8I",0,0xffff,*(game_hash(v) if v is not None else NONE for v in lod["geometry"]))
                mi=intern(models,midx,rec,36)
            parts.extend(struct.pack("<IBHBHHH",game_hash(p["label"]),p["group"],p["upgrade_group"],owner,debug,li,mi))
        added[name]=len(c["parts"])
    for off,count in ((0x20,len(attrs)//8),(0x28,len(owners)//4),(0x30,len(models)//36),(0x38,len(parts)//14)):
        struct.pack_into("<I",hdr,off,count)
    # The original byte prefixes of all reference tables remain identical.
    for tag,data,count in ((ATTR,attrs,na*8),(OWNER,owners,no*4),(MODEL,models,nm*36),(PART,parts,np*14),
                          (STR,strings,len(original[STR])),(LIST,lists,len(original[LIST]))):
        if data[:count]!=original[tag][:count]:
            raise ValueError(f"original part data changed {tag:#x}")
    custom_body=bytearray(struct.pack("<I",len(custom)))
    for key,(name,kind) in custom.items():
        custom_body.extend(name.encode("utf-8")+b"\0"+struct.pack("<II",key,kind))
    new={HDR:bytes(hdr),ATTR:attrs,OWNER:owners,MODEL:models,PART:parts,STR:strings,LIST:lists,CUSTOM:custom_body}
    order=list(original)
    if CUSTOM not in original and custom:
        order.append(CUSTOM)
    output=b"".join(block(tag,pad_like(new[tag],original.get(tag,b""))) for tag in order)
    return block(native.PART_TAG,output),{"original_parts":np,"added_parts":sum(added.values()),"new_parts":len(parts)//14,
           "original_owners":no,"new_owners":len(owners)//4,"new_attributes":len(attrs)//8,
           "new_models":len(models)//36,"string_words":len(strings)//4,"list_words":len(lists)//2,"cars":added}


def build(game, batch):
    report=json.loads((batch/"report.json").read_text(encoding="utf-8"))
    if report["errors"] or report.get("missing_vehicles") or report.get("game_table_error"):
        raise ValueError("batch is incomplete or contains errors")
    rows=sorted((r for r in report["vehicles"] if r["status"]=="native_type_and_skin_preview"),key=lambda r:r["proposed_index"])
    if len(rows)!=12 or [r["proposed_index"] for r in rows]!=list(range(46,58)):
        raise ValueError("expected all 12 addons with sequential indices 46..57")
    globalb=native.load_global(native.child(native.child(game,"GLOBAL"),"GLOBALB.LZC"))
    tb,te=native.unique_chunk(globalb,native.TYPE_TAG)
    sb,se=native.unique_chunk(globalb,native.SKIN_TAG)
    pb,pe=native.unique_chunk(globalb,native.PART_TAG)
    type_body=bytearray(globalb[tb:te])
    skin_body=bytearray(globalb[sb:se])
    collections=[]
    seen=set()
    for row in rows:
        car=row["car"]
        if not re.fullmatch(r"[A-Z0-9_]{1,31}",car):
            raise ValueError("invalid car identifier")
        files={r["path"]:r for r in row["files"]}
        def verified(name):
            r=files[name]
            path=batch/car/name
            if path.stat().st_size!=r["bytes"] or not 0<=r["bytes"]<=256*1024*1024:
                raise ValueError(f"size mismatch: {car}/{name}")
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=r["sha256"]:
                raise ValueError(f"hash mismatch: {car}/{name}")
            return data
        raw=verified("decoded/CarTypeInfos.bin")
        rawparts=verified("decoded/DBModelParts.bin")
        _,rec,skins=native.native_plan(globalb,car,raw,rawparts)
        rec,skins=bytearray(rec),bytearray(skins)
        idx=row["proposed_index"]
        struct.pack_into("<I",rec,0x840,idx)
        for i in range(0,len(skins),native.SKIN):
            struct.pack_into("<I",skins,i,idx)
        if rec!=verified("native/CarTypeInfo.record") or skins!=verified("native/SkinInfo.records"):
            raise ValueError("native preview differs from verified source")
        h=native.u32(rec,0xd0)
        if h in seen:
            raise ValueError("addon car hash collision")
        seen.add(h)
        type_body.extend(rec)
        skin_body.extend(skins)
        collections.append(parse_parts(rawparts,car))
    db,stats=merge_parts(globalb[pb:pe],collections)
    stats.update({"status":"offline_native_chunks_only","playable":False,"types":58,
                  "base_globalb_sha256":hashlib.sha256(globalb).hexdigest(),
                  "regional_not_installed":[r["car"] for r in report["vehicles"] if r["status"]=="regional_assets_only"]})
    return {"CarTypeInfo.chunk":block(native.TYPE_TAG,type_body),
            "SkinInfo.chunk":block(native.SKIN_TAG,skin_body),"DBModelParts.chunk":db},stats


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch",required=True,type=Path)
    p.add_argument("--game",type=Path,default=ROOT/".nfsu2-local"/"game")
    a=p.parse_args()
    try:
        chunks,stats=build(a.game,a.batch)
        parent=ROOT/".nfsu2-local"/"database-previews"
        parent.mkdir(parents=True,exist_ok=True)
        output=Path(tempfile.mkdtemp(prefix="db-",dir=parent))
        for name,data in chunks.items():
            (output/name).write_bytes(data)
        (output/"report.json").write_text(json.dumps(stats,indent=2)+"\n")
        print(json.dumps(stats,indent=2))
        print("Preview:",output)
        print("NOT INSTALLED: native chunks are isolated; runtime expansion still required.")
    except (ValueError,OSError,KeyError,IndexError,struct.error) as e:
        p.exit(1,f"Database preview rejected: {e}\n")


if __name__=="__main__":
    main()
