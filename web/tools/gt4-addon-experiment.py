#!/usr/bin/env python3
"""Create an independent addon build workspace; optionally compile WASM.

Original game, gen/, out/, browser profiles and shared lift cache are not
replaced. This tool deliberately does not launch a server or a game.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def overlay_files(overlay):
    report=json.loads((overlay/"report.json").read_text())
    if report["status"]!="isolated_overlay_only" or report["playable"] or report["types"]!=58:
        raise ValueError("expected verified experimental 58-type overlay")
    stock=report["stock_list_audit"]
    if not stock["fits_stock_array_by_filter"] or stock["eligible_stock_count"]>48:
        raise ValueError("stock list capacity exceeded")
    result=[]
    names=set()
    for row in report["files"]:
        path=PurePosixPath(row["path"])
        if path.is_absolute() or ".." in path.parts or str(path) in names:
            raise ValueError("invalid or duplicate overlay path")
        names.add(str(path))
        if str(path) not in ("SPEED2.EXE","GLOBAL/GLOBALB.LZC") and not (
            len(path.parts)==3 and path.parts[0]=="CARS" and
            path.name in ("GEOMETRY.BIN","TEXTURES.BIN","VINYLS.BIN","PARTS_ANIMATIONS.BIN")):
            raise ValueError("unexpected overlay member")
        src=overlay.joinpath(*path.parts)
        if not src.is_file() or src.is_symlink() or src.stat().st_size!=row["bytes"] or digest(src)!=row["sha256"]:
            raise ValueError(f"overlay integrity mismatch: {path}")
        result.append((path,src))
    if not {"SPEED2.EXE","GLOBAL/GLOBALB.LZC"}<=names:
        raise ValueError("missing core overlay files")
    return result


def destination(game,path):
    # Original disc extractions can use mixed case on Linux.
    target=game
    for part in path.parts:
        matches=[p for p in target.iterdir() if p.name.casefold()==part.casefold()] if target.is_dir() else []
        if len(matches)>1:
            raise ValueError(f"ambiguous case-insensitive copy path {target}/{part}")
        target=matches[0] if matches else target/part
    if not target.resolve().is_relative_to(game.resolve()):
        raise ValueError("overlay path escapes private copy")
    return target


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--overlay",required=True,type=Path)
    p.add_argument("--game",default=ROOT/".nfsu2-local"/"game",type=Path)
    p.add_argument("--build",action="store_true")
    a=p.parse_args()
    try:
        files=overlay_files(a.overlay.resolve())
        original=a.game.resolve()
        if digest(original/"SPEED2.EXE")!="f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7":
            raise ValueError("original executable hash mismatch")
        for name in (".venv","deps"):
            if not (ROOT/name).is_dir():
                raise ValueError(f"missing existing build dependencies: {name}")
        parent=ROOT/".nfsu2-local"/"experiments"
        parent.mkdir(parents=True,exist_ok=True)
        output=Path(tempfile.mkdtemp(prefix="gt4-",dir=parent))
        checkout=output/"source"
        game=output/"game"
        print("EXPERIMENT:",output,flush=True)
        subprocess.run(["git","-C",str(ROOT),"worktree","add","--detach",str(checkout),"HEAD"],check=True)
        # Copy real file contents, never hardlink retail assets to the experiment.
        subprocess.run(["cp","-aL","--reflink=auto",str(original),str(game)],check=True)
        for path,src in files:
            target=destination(game,path)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,target)
        for name in (".venv","deps"):
            (checkout/name).symlink_to(ROOT/name,target_is_directory=True)
        for name in ("gen/all","gen/server"):
            (checkout/name).mkdir(parents=True,exist_ok=True)
        # WEB_LIFT explicitly set disables shared generated-code cache read/write.
        # Private gen/ and out/ prevent the original working build being replaced.
        env=dict(os.environ,WEB_LIFT="opt",NFSU2_LIFT_WORKERS="1",J="1",
                 OBJCACHE=str(output/"object-cache"))
        print("Private data:",game,flush=True)
        print("Private source:",checkout,flush=True)
        if a.build:
            subprocess.run(["bash","web/gen.sh",str(game/"SPEED2.EXE")],cwd=checkout,env=env,check=True)
            subprocess.run(["bash","web/build.sh"],cwd=checkout,env=env,check=True)
            wasm=checkout/"out/web/nfsu2.wasm"
            if not wasm.is_file():
                raise ValueError("build did not produce WASM")
            print("Experimental WASM:",wasm,flush=True)
        print("ORIGINAL GAME AND BUILD UNCHANGED.")
        print("NOT GAMEPLAY VALIDATED: no server started; keep profiles separate.")
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError) as e:
        p.exit(1,f"Experiment stopped: {e}\n")


if __name__=="__main__":
    main()
