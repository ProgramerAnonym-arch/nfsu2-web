#!/usr/bin/env python3
"""Batch-stage the four supplied NFSU2 addon pack layouts, never install them.

All output is private under .nfsu2-local/batch-previews. The original ZIPs,
game data, runtime and saves remain untouched. Native type/skin previews are
not a playable installation; DBModelParts must still be merged by a later tool.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import struct
import tempfile
import zipfile
from gt4_addon_parts import parse_parts

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAX = 256 * 1024 * 1024


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stage = load_tool("gt4-addon-stage.py", "stage")
native = load_tool("gt4-addon-native-preview.py", "native")
OLYMPIC = ("IMPREZA", "INTEGRA", "LANCER", "NEONC", "NSX", "S2000", "CHARGER")
BAYVIEW = ("CIVICEG", "CORVETTEC5", "INFIFX45", "GS300")
REGIONAL = ("CIVIC", "CORSA", "PEUGOT106", "RSX")


def decode(data, tag):
    if len(data) < 36:
        raise ValueError("truncated collection")
    magic, size, version, manager, packed = struct.unpack_from("<5I", data)
    if (magic, size, version, manager, packed) != (0x42704D67, len(data)-8, 3, tag, len(data)-20):
        raise ValueError("unsupported Binary collection header/manager")
    src = data[20:]
    if src.startswith(b"RAWW\x01\x10"):
        count, length = struct.unpack_from("<II", src, 8)
        if length != len(src) or count != len(src)-16 or not 0 < count <= stage.MAX_DB:
            raise ValueError("invalid RAWW length")
        return src[16:]
    return stage.decode_export(data)


class Archive:
    def __init__(self, z):
        self.z = z
        self.entries = {}
        for item in z.infolist():
            if item.is_dir():
                continue
            key = item.filename.replace("\\", "/").casefold()
            if key in self.entries:
                raise ValueError(f"duplicate ZIP entry: {key}")
            self.entries[key] = item

    def matches(self, suffix, prefix=""):
        suffix = suffix.casefold()
        return [k for k in self.entries if k.startswith(prefix.casefold())
                and (k == suffix or k.endswith("/"+suffix))]

    def read(self, key):
        item = self.entries[key]
        if not 0 < item.file_size <= MAX:
            raise ValueError(f"unsupported member size: {key}")
        return self.z.read(item)

    def one(self, suffix, prefix="", optional=False):
        keys = self.matches(suffix, prefix)
        if optional and not keys:
            return None
        if len(keys) != 1:
            raise ValueError(f"{suffix}: expected one ZIP entry, got {len(keys)}")
        return self.read(keys[0])

    def assets(self, car, prefix=""):
        out = {}
        for filename in ("GEOMETRY.BIN", "TEXTURES.BIN", "VINYLS.BIN", "PARTS_ANIMATIONS.BIN"):
            data = self.one(f"{car}/{filename}", prefix, optional=filename not in ("GEOMETRY.BIN", "TEXTURES.BIN"))
            if data is not None:
                out[f"CARS/{car}/{filename}"] = data
        return out

    def metadata(self, prefix, out):
        # Preserve scripts/config/auxiliary resources as inert data in a private
        # preview. Never use the archive path as a filesystem path.
        for k in self.entries:
            if not k.startswith(prefix.casefold()):
                continue
            p = PurePosixPath(k)
            if p.suffix in (".ini", ".end", ".dds", ".gin", ".abk") or any(
                    s in p.parts for s in ("slotoverrides", "materials", "slottypeoverrides")):
                out["metadata/" + hashlib.sha256(k.encode()).hexdigest()[:16] + "-" + p.name] = self.read(k)


def type_table(data):
    b, e = native.unique_chunk(data, native.TYPE_TAG)
    start = b + (-b) % 16
    if (e-start) % native.TYPE:
        raise ValueError("unsupported native type table alignment")
    rows = [data[i:i+native.TYPE] for i in range(start, e, native.TYPE)]
    names = [native.name_at(r, 0, 32) for r in rows]
    if len(names) != len(set(names)) or any(native.u32(r, 0x840) != i for i,r in enumerate(rows)):
        raise ValueError("duplicate names or nonsequential native indices")
    return dict(zip(names, rows))


def extract_olympic_types(data, table, car):
    record = table[car]
    old = native.u32(record, 0x840)
    b, e = native.unique_chunk(data, native.SKIN_TAG)
    if (e-b) % native.SKIN:
        raise ValueError("unsupported Olympic skin table")
    return record + b"".join(data[i:i+native.SKIN] for i in range(b,e,native.SKIN)
                            if native.u32(data,i) == old)


def pack_kind(a):
    if a.matches("CIVICEK9/GEOMETRY.BIN") and a.matches("CarTypeInfos.bin"):
        return "civic"
    if a.matches("CarTypeInfos/CIVICEG.bin") and a.matches("CIVICEG/GEOMETRY.BIN"):
        return "bayview"
    if a.matches("BETA 2/Simple Installation/GLOBAL/GlobalB.lzc"):
        return "olympic"
    if all(a.matches(f"CARS/{car}/GEOMETRY.BIN") for car in REGIONAL):
        return "regional"
    return None


def batch(source, game, output):
    base = None
    base_error = None
    try:
        path = native.child(native.child(game, "GLOBAL"), "GLOBALB.LZC")
        base = native.load_global(path)
        stock = type_table(base)
    except (OSError, ValueError, KeyError, IndexError, struct.error, SystemExit) as e:
        base_error = str(e)
        stock = {}
    result = {"status":"preview_only", "playable":False, "game_table_error":base_error,
              "stock_type_count":len(stock), "vehicles":[], "ignored_archives":[], "errors":[]}
    seen = set()
    next_index = len(stock)
    candidates = []
    # Prefer deterministic order for future shared index allocation.
    archives = sorted((p for p in source.rglob("*") if p.is_file() and p.suffix.casefold() == ".zip"), key=lambda p: str(p).casefold())
    result["scanned_archives"] = [str(p) for p in archives]
    for path in archives:
        try:
            with zipfile.ZipFile(path) as z:
                a = Archive(z)
                kind = pack_kind(a)
                if not kind:
                    result["ignored_archives"].append(str(path))
                    continue
                candidates.append((("civic","bayview","olympic","regional").index(kind),path,kind))
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            result["errors"].append({"archive":str(path),"error":str(e)})
    for _,path,kind in sorted(candidates):
        try:
            with zipfile.ZipFile(path) as z:
                a = Archive(z)
                cars = {"civic":("CIVICEK9",), "bayview":BAYVIEW, "olympic":OLYMPIC, "regional":REGIONAL}[kind]
                olympic = table = None
                if kind == "olympic":
                    olympic = a.one("BETA 2/Simple Installation/GLOBAL/GlobalB.lzc")
                    if olympic.startswith(b"JDLZ"):
                        if not 0 < native.u32(olympic,8) <= MAX:
                            raise ValueError("Olympic GLOBALB too large")
                        olympic = native.jdlz(olympic)
                    table = type_table(olympic)
                for car in cars:
                    if car in seen:
                        result["errors"].append({"car":car,"archive":str(path),"error":"duplicate pack/car; first successful stage retained"})
                        continue
                    entry = {"car":car,"pack":kind,"archive":str(path),"playable":False}
                    try:
                        prefix = ""
                        if kind == "olympic":
                            key = a.matches(f"BETA 2/_Main Files/CARS/{car}/GEOMETRY.BIN")
                            if len(key) != 1:
                                raise ValueError("missing or duplicate Beta 2 geometry")
                            prefix = key[0].split("beta 2/")[0] + "beta 2/"
                        assets = a.assets(car,prefix)
                        if kind == "civic":
                            t = a.one("CarTypeInfos.bin")
                            p = a.one("DBModelParts.bin")
                        elif kind == "bayview":
                            t = a.one(f"CarTypeInfos/{car}.bin")
                            p = a.one(f"DBModelParts/{car}.bin")
                        elif kind == "olympic":
                            t = None
                            p = a.one(f"Advanced Installation/Binary/CarParts/{car}.bin",prefix)
                        else:
                            t = p = None
                        if kind != "regional":
                            raw_t = decode(t,0x579512f6) if t is not None else extract_olympic_types(olympic,table,car)
                            raw_p = decode(p,0x768c36c0)
                            if native.name_at(raw_t,0,32) != car or raw_p.split(b"\0",1)[0] != car.encode():
                                raise ValueError("collection identity mismatch")
                            assets["decoded/CarTypeInfos.bin"] = raw_t
                            assets["decoded/DBModelParts.bin"] = raw_p
                            if t is not None:
                                assets["binary/CarTypeInfos.bin"] = t
                            assets["binary/DBModelParts.bin"] = p
                            if kind == "bayview":
                                key = a.matches(f"CarTypeInfos/{car}.bin")[0]
                                a.metadata(key.rsplit("/",2)[0]+"/",assets)
                            else:
                                for key in a.matches(f"UnlimiterData/{car}.ini",prefix):
                                    assets[f"config/{car}.ini"] = a.read(key)
                                for key in a.matches(f"CarTypeMapping/{car}.ini",prefix):
                                    assets[f"sound/{car}.ini"] = a.read(key)
                            parts = parse_parts(raw_p, car)
                            entry["exported_part_count"] = parts["count"]
                            entry["parts_status"] = "parsed_all_records"
                            assets["decoded/DBModelParts.json"] = (json.dumps(parts, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
                            if base is None:
                                entry["status"] = "staged_no_base_table"
                            elif car in stock:
                                entry["status"] = "staged_conflicts_with_existing_type"
                            else:
                                try:
                                    report, rec, skins = native.native_plan(base,car,raw_t,raw_p)
                                    rec, skins = bytearray(rec),bytearray(skins)
                                    struct.pack_into("<I",rec,0x840,next_index)
                                    for at in range(0,len(skins),native.SKIN):
                                        struct.pack_into("<I",skins,at,next_index)
                                    assets["native/CarTypeInfo.record"] = bytes(rec)
                                    assets["native/SkinInfo.records"] = bytes(skins)
                                    entry["status"] = "native_type_and_skin_preview"
                                    entry["proposed_index"] = next_index
                                    entry["manufacturer"] = report["manufacturer"]
                                except (ValueError, KeyError, IndexError, struct.error) as e:
                                    entry["status"] = "staged_native_preview_rejected"
                                    entry["native_error"] = str(e)
                        else:
                            entry["status"] = "regional_assets_only"
                            entry["type_already_present"] = car in stock if base is not None else None
                            try:
                                folder = native.child(native.child(game,"CARS"),car)
                                entry["original_geometry_present"] = native.child(folder,"GEOMETRY.BIN").is_file()
                            except (OSError, ValueError):
                                entry["original_geometry_present"] = False
                        target = output/car
                        with tempfile.TemporaryDirectory(dir=output) as temp:
                            work = Path(temp)/car
                            work.mkdir()
                            entry["files"] = []
                            for name,data in sorted(assets.items()):
                                file = work/name
                                file.parent.mkdir(parents=True,exist_ok=True)
                                file.write_bytes(data)
                                entry["files"].append({"path":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
                            (work/"manifest.json").write_text(json.dumps(entry,indent=2)+"\n")
                            work.rename(target)
                        if "proposed_index" in entry:
                            next_index += 1
                        seen.add(car)
                        result["vehicles"].append(entry)
                    except (OSError, ValueError, KeyError, IndexError, struct.error, RuntimeError, zipfile.BadZipFile, SystemExit) as e:
                        result["errors"].append({"car":car,"archive":str(path),"error":str(e)})
        except (OSError, ValueError, KeyError, IndexError, struct.error, RuntimeError, zipfile.BadZipFile, SystemExit) as e:
            result["errors"].append({"archive":str(path),"error":str(e)})
    result["missing_packs"] = sorted(set(("civic","bayview","olympic","regional")) - {kind for _,_,kind in candidates})
    result["missing_vehicles"] = sorted(set(("CIVICEK9",) + BAYVIEW + OLYMPIC + REGIONAL) - seen)
    result["proposed_type_count"] = next_index if base is not None else None
    (output/"report.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,default=ROOT/".nfsu2-local")
    p.add_argument("--game",type=Path,default=ROOT/".nfsu2-local"/"game")
    args = p.parse_args()
    if not args.source.is_dir():
        p.error(f"ZIP source directory not found: {args.source}")
    parent = ROOT/".nfsu2-local"/"batch-previews"
    parent.mkdir(parents=True,exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="batch-",dir=parent))
    report = batch(args.source,args.game,output)
    for row in report["vehicles"]:
        print(row["car"],row["status"],row.get("proposed_index",""),row.get("native_error",""))
    for row in report["errors"]:
        print("ERROR",row)
    if report["game_table_error"]:
        print("BASE TABLE ERROR:",report["game_table_error"])
    for kind in report["missing_packs"]:
        print("MISSING PACK:",kind)
    for car in report["missing_vehicles"]:
        print("MISSING VEHICLE:",car)
    print("ZIP archives scanned:",len(report["scanned_archives"]))
    print("Staged:",len(report["vehicles"]),"Native previews:",sum("proposed_index" in r for r in report["vehicles"]))
    print("Report:",output/"report.json")
    print("NOT INSTALLED: original game and saves untouched.")
    return int(not report["vehicles"] or bool(report["missing_vehicles"]) or bool(report["errors"]) or bool(report["game_table_error"])
               or any(r["status"]=="staged_native_preview_rejected" for r in report["vehicles"]))


if __name__=="__main__":
    raise SystemExit(main())
