#!/usr/bin/env python3
"""Prepare native CarTypeInfo/SkinInfo records in an isolated preview directory.

This does NOT install cars or edit GLOBALB, nor does it expand the runtime.
The record layout is independently documented in the NFSU2Unity
cartypeinfo-and-parts notes and Nikki's Underground2 CarTypeInfo serializer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from texpacks import jdlz

TYPE = 0x890
SKIN = 0x40
TYPE_TAG = 0x34600
SKIN_TAG = 0x34601
PART_TAG = 0x80034602
MAX_GLOBAL = 128 * 1024 * 1024


def u32(data, pos):
    return struct.unpack_from("<I", data, pos)[0]


def hash_name(name):
    h = 0xffffffff
    for b in name.encode("ascii"):
        h = (33 * h + b) & 0xffffffff
    return h


def name_at(data, at, size):
    return data[at:at + size].split(b"\0", 1)[0].decode("ascii")


def child(parent, name):
    found = [p for p in parent.iterdir() if p.name.lower() == name.lower()]
    if len(found) != 1:
        raise ValueError(f"{parent}/{name}: expected one match, found {len(found)}")
    return found[0]


def load_global(path):
    if not 0 < path.stat().st_size <= MAX_GLOBAL:
        raise ValueError("unsupported GLOBALB file size")
    data = path.read_bytes()
    if data.startswith(b"JDLZ"):
        if len(data) < 16 or data[4:6] != b"\x02\x10" or not 0 < u32(data, 8) <= MAX_GLOBAL:
            raise ValueError("unsupported GLOBALB compression")
        if u32(data, 12) != len(data):
            raise ValueError("GLOBALB JDLZ compressed size mismatch")
        data = jdlz(data)
    return data


def top_chunks(data):
    at = 0
    while at + 8 <= len(data):
        tag, size = struct.unpack_from("<II", data, at)
        end = at + 8 + size
        if end > len(data):
            raise ValueError(f"truncated chunk at {at:#x}")
        yield tag, at + 8, end
        at = end
    if at != len(data) and any(data[at:]):
        raise ValueError("nonzero trailing GLOBALB bytes")


def unique_chunk(data, tag):
    hits = [(b, e) for t, b, e in top_chunks(data) if t == tag]
    if len(hits) != 1:
        raise ValueError(f"expected exactly one top-level chunk {tag:#x}, found {len(hits)}")
    return hits[0]


def native_plan(globalb, car, exported_type, exported_parts):
    if not re.fullmatch(r"[A-Z0-9_]{1,31}", car):
        raise ValueError("invalid car ID")
    b, e = unique_chunk(globalb, TYPE_TAG)
    pad = (-b) % 16
    if e < b + pad or (e - b - pad) % TYPE:
        raise ValueError("CarTypeInfo chunk alignment/size differs from supported layout")
    stock = [globalb[i:i + TYPE] for i in range(b + pad, e, TYPE)]
    # This preview is intentionally restricted to the stock NA v1.2 table.
    # Do not guess at layouts in other game revisions or already-modded files.
    if len(stock) != 46:
        raise ValueError(f"expected 46 original types; actual count {len(stock)}")
    ids = [name_at(r, 0, 0x20) for r in stock]
    hashes = [u32(r, 0xd0) for r in stock]
    if any(u32(r, 0x840) != i for i, r in enumerate(stock)):
        raise ValueError("original type indices are not sequential")
    if car.upper() in [x.upper() for x in ids] or hash_name(car) in hashes:
        raise ValueError("new car name or hash collides with original table")
    sb, se = unique_chunk(globalb, SKIN_TAG)
    if (se - sb) % SKIN:
        raise ValueError("original SkinInfo chunk size differs from supported layout")
    pb, pe = unique_chunk(globalb, PART_TAG)
    if len(exported_type) < TYPE or (len(exported_type) - TYPE) % SKIN:
        raise ValueError("exported CarTypeInfo/SkinInfo size mismatch")
    record = bytearray(exported_type[:TYPE])
    old = u32(record, 0x840)
    if name_at(record, 0, 0x20) != car or name_at(record, 0x20, 0x20) != car:
        raise ValueError("exported car names do not match")
    if u32(record, 0xd0) != hash_name(car):
        raise ValueError("exported car hash mismatch")
    if u32(record, 0x844) != 0:
        raise ValueError("only racer-type addons supported")
    if name_at(record, 0x40, 0x20).upper() != f"CARS\\{car}\\GEOMETRY.BIN":
        raise ValueError("unexpected geometry path")
    new = len(stock)
    skins = bytearray(exported_type[TYPE:])
    skin_ids = []
    for at in range(0, len(skins), SKIN):
        if u32(skins, at) != old:
            raise ValueError("exported skin car index mismatch")
        number = u32(skins, at + 4)
        if not 1 <= number <= 10 or number in skin_ids:
            raise ValueError("invalid/duplicate skin number")
        skin_ids.append(number)
        struct.pack_into("<I", skins, at, new)
    expected = [i + 1 for i, val in enumerate(record[0x880:0x88a]) if val]
    if sorted(skin_ids) != expected:
        raise ValueError("skin records disagree with available skin flags")
    struct.pack_into("<I", record, 0x840, new)
    terminator = exported_parts.find(b"\0")
    if terminator < 0 or exported_parts[:terminator] != car.encode() or len(exported_parts) < terminator + 5:
        raise ValueError("exported DBModelParts identity mismatch")
    count = u32(exported_parts, terminator + 1)
    if not 0 < count <= 65535:
        raise ValueError("unexpected exported part count")
    report = {
        "status": "native_record_preview_only",
        "playable": False,
        "car": car,
        "manufacturer": name_at(record, 0xc0, 0x10),
        "hash": f"0x{hash_name(car):08x}",
        "source_index": old,
        "proposed_index": new,
        "original_type_count": len(stock),
        "original_type_names": ids,
        "proposed_type_count": new + 1,
        "original_skin_count": (se - sb) // SKIN,
        "addon_skin_count": len(skin_ids),
        "exported_part_count": count,
        "original_parts_chunk_bytes": pe - pb,
        "game_price": u32(record, 0x87c),
        "blockers": [
            "DBModelParts: decode individual parts and merge with native tables",
            "CarTypeInfo array limits, stock-car list and career unlock logic",
            "Collision volume, sound mapping, frontend label/logo, gameplay and save tests"
        ]
    }
    return report, bytes(record), bytes(skins)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=ROOT / ".nfsu2-local" / "game")
    parser.add_argument("--car", required=True, type=str.upper)
    parser.add_argument("--write-preview", action="store_true")
    a = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Z0-9_]{1,31}", a.car):
            raise ValueError("invalid car ID")
        stage = ROOT / ".nfsu2-local" / "addons" / a.car
        manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("car") != a.car or manifest.get("status") != "staged_only":
            raise ValueError("invalid stage manifest")
        files = {r["path"]: r for r in manifest["files"]}

        def read_stage(name):
            f = files[name]
            path = stage / name
            if not 0 < path.stat().st_size <= 256 * 1024 * 1024:
                raise ValueError(f"staged file too large or empty: {name}")
            data = path.read_bytes()
            if len(data) != f["bytes"] or hashlib.sha256(data).hexdigest() != f["sha256"]:
                raise ValueError(f"staged file integrity mismatch: {name}")
            return data

        path = child(child(a.game, "GLOBAL"), "GLOBALB.LZC")
        data = load_global(path)
        report, record, skins = native_plan(
            data, a.car, read_stage("decoded/CarTypeInfos.bin"), read_stage("decoded/DBModelParts.bin")
        )
        geometry = read_stage(f"CARS/{a.car}/GEOMETRY.BIN")
        # Marker scan is a diagnostic only: no marker is NOT proof that a collision volume
        # is absent from all game resources, and finding a marker is not a validation.
        report["geometry_collision_chunk_marker"] = b"\x20\x40\x03\x80" in geometry
        report["geometry_car_cv_name_marker"] = (a.car + "_CV").encode() in geometry
        report["globalb_unpacked_sha256"] = hashlib.sha256(data).hexdigest()
        report["native_type_sha256"] = hashlib.sha256(record).hexdigest()
        if a.write_preview:
            parent = ROOT / ".nfsu2-local" / "native-preview"
            parent.mkdir(parents=True, exist_ok=True)
            dest = parent / a.car
            if dest.exists() or dest.is_symlink():
                raise ValueError(f"preview already exists: {dest}")
            with tempfile.TemporaryDirectory(prefix=".preview-", dir=parent) as temp:
                work = Path(temp) / a.car
                work.mkdir()
                (work / "CarTypeInfo.record").write_bytes(record)
                (work / "SkinInfo.records").write_bytes(skins)
                (work / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                if dest.exists() or dest.is_symlink():
                    raise ValueError(f"preview already exists: {dest}")
                work.rename(dest)
            print(f"Private preview: {dest}")
        print(json.dumps(report, indent=2))
        print("NOT INSTALLED: GLOBALB and saves are unchanged.")
    except (OSError, ValueError, KeyError, IndexError, struct.error) as e:
        parser.exit(1, f"Preview rejected: {e}\n")


if __name__ == "__main__":
    main()
