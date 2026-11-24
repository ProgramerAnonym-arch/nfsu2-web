#!/usr/bin/env python3
"""Repair only the experimental GLOBALB compression, without a WASM rebuild.

Run with the experimental server stopped. No retail files or saved profiles
are edited. Preserve the prior compressed bytes outside the served game folder.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location("overlay",HERE/"gt4-addon-overlay-preview.py")
overlay=importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
native=overlay.native
EXPECTED_RAW="b5028d236bfd5f59a687613cae3f122a0bcc1fa672ed1afd2878268897213330"
EXE_STOCK="f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment",required=True,type=Path)
    a=p.parse_args()
    try:
        exp=a.experiment.resolve()
        parent=(ROOT/".nfsu2-local"/"experiments").resolve()
        if exp.parent!=parent or not exp.name.startswith("gt4-"):
            raise ValueError("only a private experimental workspace is permitted")
        game=exp/"game"
        if game.is_symlink() or (game/"GLOBAL").is_symlink() or not (exp/"source"/"out/web/nfsu2.wasm").is_file():
            raise ValueError("expected private compiled experiment")
        if sha((game/"SPEED2.EXE").read_bytes())==EXE_STOCK:
            raise ValueError("refusing to edit a retail installation")
        target=native.child(native.child(game,"GLOBAL"),"GLOBALB.LZC")
        if target.is_symlink() or not target.resolve().is_relative_to(exp):
            raise ValueError("invalid experimental GLOBALB path")
        old=target.read_bytes()
        raw=native.load_global(target)
        if sha(raw)!=EXPECTED_RAW:
            raise ValueError("unexpected unpacked database; no files written")
        decoded,why=overlay.jdlz_native(old)
        print("Old JDLZ:",len(old),"bytes; runtime validation:",why or "OK",flush=True)
        print("Unpacked:",len(raw),"bytes; SHA256:",sha(raw),flush=True)
        if decoded==raw and len(old)<len(raw):
            print("Already repaired; no changes.")
            return
        print("Recompressing with game-compatible encoder...",flush=True)
        packed=overlay.pack_globalb(raw)
        backup=exp/"GLOBALB.before-compression-fix.LZC"
        if backup.exists():
            if backup.read_bytes()!=old:
                raise ValueError("existing backup differs; refusing overwrite")
        else:
            with backup.open("xb") as f:
                f.write(old)
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix=".globalb-",delete=False) as tmp:
            tmp.write(packed)
            name=Path(tmp.name)
        try:
            if native.load_global(name)!=raw or overlay.jdlz_native(name.read_bytes())!=(raw,None):
                raise ValueError("re-read validation failed")
            os.replace(name,target)
        finally:
            name.unlink(missing_ok=True)
        report={"status":"compression_repaired","old_bytes":len(old),"new_bytes":len(packed),
                "unpacked_bytes":len(raw),"unpacked_sha256":sha(raw),"packed_sha256":sha(packed),
                "old_native_rejection":why,"strict_runtime_roundtrip":True}
        (exp/"compression-fix.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,indent=2))
        print("Original game and WASM unchanged. Restart experimental server and test.")
    except (OSError,ValueError,KeyError) as e:
        p.exit(1,f"Compression repair rejected: {e}\n")


if __name__=="__main__":
    main()
