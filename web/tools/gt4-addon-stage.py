#!/usr/bin/env python3
"""Inspect and privately stage Binary/Unlimiter addon assets; NOT an installer.

Usage:
  python3 web/tools/gt4-addon-stage.py PATH.zip --car CIVICEK9
  python3 web/tools/gt4-addon-stage.py PATH.zip --car CIVICEK9 --stage

Only a single-car Binary v3 export with a CarTypeInfos and DBModelParts node
is supported. No .end/.asi/.exe is executed. The original game is never edited.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MAX_ASSET = 256 * 1024 * 1024
MAX_DB = 16 * 1024 * 1024


def decode_export(data):
    """Binary v3 collection envelope, as seen in the Civic EK9 package."""
    if len(data) < 36:
        raise ValueError("truncated Binary export")
    magic, size, version, checksum, packed = struct.unpack_from("<5I", data)
    if magic != 0x42704D67 or size != len(data) - 8 or version != 3 or packed != len(data) - 20:
        raise ValueError("unsupported Binary export envelope")
    src = data[20:]
    if src[:6] != b"JDLZ\x02\x10":
        raise ValueError("unsupported compression")
    expected, length = struct.unpack_from("<II", src, 8)
    if length != len(src) or not 0 < expected <= MAX_DB:
        raise ValueError("invalid JDLZ sizes")
    i, f1, f2 = 16, 1, 1
    out = bytearray()

    def take():
        nonlocal i
        if i >= len(src):
            raise ValueError("truncated JDLZ block")
        b = src[i]
        i += 1
        return b

    while len(out) < expected:
        if f1 == 1:
            f1 = take() | 256
        if f2 == 1:
            f2 = take() | 256
        if f1 & 1:
            a, b = take(), take()
            if f2 & 1:
                count, distance = (b | ((a & 240) << 4)) + 3, (a & 15) + 1
            else:
                distance, count = (b | ((a & 224) << 3)) + 17, (a & 31) + 3
            if distance > len(out) or len(out) + count > expected:
                raise ValueError("JDLZ back-reference out of bounds")
            for _ in range(count):
                out.append(out[-distance])
            f2 >>= 1
        else:
            out.append(take())
        f1 >>= 1
    return bytes(out)


def inspect(archive, car):
    if not re.fullmatch(r"[A-Z0-9_]{1,31}", car):
        raise ValueError("invalid car ID")
    with zipfile.ZipFile(archive) as z:
        entries = [i for i in z.infolist() if not i.is_dir()]

        def find(suffix, required=True, limit=MAX_ASSET):
            want = tuple(s.lower() for s in PurePosixPath(suffix).parts)
            matches = []
            for item in entries:
                parts = PurePosixPath(item.filename.replace("\\", "/")).parts
                if tuple(p.lower() for p in parts[-len(want):]) == want:
                    matches.append(item)
            if not matches and not required:
                return None
            if len(matches) != 1:
                raise ValueError(f"{suffix}: expected one entry, found {len(matches)}")
            item = matches[0]
            if not 0 < item.file_size <= limit:
                raise ValueError(f"{suffix}: invalid size")
            return z.read(item)  # zipfile verifies the member CRC

        assets = {}
        for name in ("GEOMETRY.BIN", "TEXTURES.BIN", "VINYLS.BIN"):
            data = find(f"{car}/{name}", required=name != "VINYLS.BIN")
            if data is not None:
                assets[f"CARS/{car}/{name}"] = data
        for name in ("CarTypeInfos.bin", "DBModelParts.bin"):
            data = find(name, limit=MAX_DB)
            decoded = decode_export(data)
            identity = decoded.split(b"\0", 1)[0]
            if identity != car.encode("ascii"):
                raise ValueError(f"{name}: car identity differs from {car}")
            if name == "CarTypeInfos.bin" and f"CARS\\{car}\\GEOMETRY.BIN".encode() not in decoded:
                raise ValueError("CarTypeInfos does not reference the expected geometry")
            assets[f"binary/{name}"] = data
            assets[f"decoded/{name}"] = decoded
        ini = find(f"UnlimiterData/{car}.ini", required=False, limit=MAX_DB)
        if ini is not None:
            assets[f"config/{car}.ini"] = ini
        logo = find(f"SECONDARY_LOGO_{car}.dds", required=False, limit=MAX_DB)
        if logo is not None:
            assets[f"ui/SECONDARY_LOGO_{car}.dds"] = logo
    return assets


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--car", required=True, type=str.upper)
    p.add_argument("--stage", action="store_true", help="copy into ignored .nfsu2-local/addons, not the game")
    a = p.parse_args()
    try:
        assets = inspect(a.archive, a.car)
        manifest = {
            "schema": 1, "car": a.car,
            "status": "staged_only" if a.stage else "inspected_only",
            "playable": False,
            "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in sorted(assets.items())],
            "blockers": ["Binary collection conversion to native game tables",
                         "CarTypeInfo count and allocation in the guest runtime",
                         "Stock-car menu/garage records and save compatibility",
                         "Performance, unlock, render and sound compatibility"]
        }
        if a.stage:
            parent = ROOT / ".nfsu2-local" / "addons"
            parent.mkdir(parents=True, exist_ok=True)
            dest = parent / a.car
            if dest.exists() or dest.is_symlink():
                raise ValueError(f"refusing to overwrite existing stage: {dest}")
            with tempfile.TemporaryDirectory(prefix=".addon-", dir=parent) as work:
                staging = Path(work) / a.car
                staging.mkdir()
                for name, data in assets.items():
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                if dest.exists() or dest.is_symlink():
                    raise ValueError(f"refusing to overwrite existing stage: {dest}")
                staging.rename(dest)
            print(f"Staged privately: {dest}")
        print(json.dumps(manifest, indent=2))
        print("NOT INSTALLED: the game and its saves are unchanged.")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as e:
        p.exit(1, f"Addon rejected: {e}\n")


if __name__ == "__main__":
    main()
