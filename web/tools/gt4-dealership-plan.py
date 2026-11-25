#!/usr/bin/env python3
"""Prepare the native dealership integration from the actual catalog and PE.

Read-only for the game and existing saves. The output is a manufacturer
index plus the exact x86 instructions needed to design the in-game filter.
No guessed purchase price or unlock state is applied.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
ADDONS=("CIVICEK9","CIVICEG","CORVETTEC5","INFIFX45","GS300","IMPREZA",
        "INTEGRA","LANCER","NEONC","NSX","S2000","CHARGER")
# Correct known spelling variants only. Preserve native brand distinctions
# such as Honda/Acura and Nissan/Infiniti.
ALIASES={"PEUGOT":"PEUGEOT","VOLKSWAGEN":"VOLKSWAGEN","VW":"VOLKSWAGEN",
         "CORVETTE":"CHEVROLET","OLDDODGE":"DODGE"}


def dealerships(report):
    cars=report["catalog"]
    if report["status"]!="read_only_audit" or len(cars)!=58 or report["native_part_count"]!=14557:
        raise ValueError("expected the validated 58-type experimental catalog")
    if [c["index"] for c in cars]!=list(range(58)):
        raise ValueError("nonsequential native catalog")
    if tuple(c["id"] for c in cars[46:])!=ADDONS or len({c["hash"] for c in cars})!=58:
        raise ValueError("unexpected native identities")
    grouped=defaultdict(list)
    for c in cars:
        if not c["eligible"]:
            continue
        brand=" ".join(c["manufacturer"].strip().upper().split())
        brand=ALIASES.get(brand,brand) or "UNASSIGNED"
        if not re.fullmatch(r"[A-Z0-9 &._'-]{1,32}",brand):
            raise ValueError(f"invalid manufacturer field for {c['id']}: {brand!r}")
        grouped[brand].append({"id":c["id"],"type_index":c["index"],"type_hash":c["hash"],
                               "native_manufacturer":c["manufacturer"],"native_price":c["game_price"],
                               "addon":c["addon"],"physics_sha256":c["physics_sha256"]})
    count=sum(map(len,grouped.values()))
    if count!=43 or report["eligible_count"]!=count:
        raise ValueError("unexpected eligible vehicle count")
    return [{"manufacturer":brand,"vehicle_count":len(rows),
             "native_type_indices":[c["type_index"] for c in rows],
             "vehicles":sorted(rows,key=lambda c:c["type_index"])}
            for brand,rows in sorted(grouped.items())]


def inspect_exe(path):
    import pefile
    from capstone import Cs,CS_ARCH_X86,CS_MODE_32
    raw=path.read_bytes()
    if len(raw)!=4800512:
        raise ValueError("unexpected executable size")
    pe=pefile.PE(data=raw,fast_load=True)
    if pe.OPTIONAL_HEADER.ImageBase!=0x400000 or pe.FILE_HEADER.Machine!=0x14c:
        raise ValueError("expected NA x86 executable")
    dis=Cs(CS_ARCH_X86,CS_MODE_32)
    dis.detail=True
    def decode(va,n):
        sec=pe.get_section_by_rva(va-0x400000)
        if sec is None or not sec.Characteristics & 0x20000000:
            raise ValueError(f"address outside executable section: {va:#x}")
        offset=pe.get_offset_from_rva(va-0x400000)
        return list(dis.disasm(raw[offset:offset+n],va))
    def fmt(ins):
        return {"address":hex(ins.address),"bytes":ins.bytes.hex(),
                "instruction":f"{ins.mnemonic} {ins.op_str}".strip()}
    lot=decode(0x4df9c0,0x180)
    calls=[i for i,x in enumerate(lot) if x.address==0x4dfa83]
    if len(calls)!=1:
        raise ValueError("known regional check callsite is not an instruction boundary")
    i=calls[0]
    call=lot[i]
    if call.mnemonic!="call" or call.op_str!="0x5022c0":
        raise ValueError("known regional check callsite differs; no hook proposed")
    # Capture context rather than inferring which register carries the type.
    return {"exe_sha256":hashlib.sha256(raw).hexdigest(),
            "lot_builder":"0x4df9c0",
            "regional_check":"0x5022c0",
            "regional_call":hex(call.address),
            "after_call":hex(call.address+call.size),
            "call_context":[fmt(x) for x in lot[max(0,i-18):i+16]],
            "regional_entry":[fmt(x) for x in decode(0x5022c0,0x90)[:35]]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog",required=True,type=Path)
    p.add_argument("--game",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    try:
        source=json.loads(a.catalog.read_text())
        groups=dealerships(source)
        site=inspect_exe(a.game/"SPEED2.EXE")
        report={"status":"native_dealership_plan_only","playable_filter":False,
                "manufacturers":groups,"vehicle_count":43,"integration":site,
                "policy":{"selection":"native stock list; retain region and unlock rules",
                          "economy":"original purchase and trade rules remain unchanged",
                          "prices":"native fields only, not yet connected to transactions"}}
        with a.output.open("x",encoding="utf-8") as f:
            json.dump(report,f,indent=2)
            f.write("\n")
        print("DEALERSHIPS:")
        for g in groups:
            print(g["manufacturer"],g["vehicle_count"],":",", ".join(c["id"] for c in g["vehicles"]))
        print("NATIVE FILTER CALLSITE:")
        for row in site["call_context"]:
            print(row["address"],row["instruction"])
        print("REGIONAL CHECK:")
        for row in site["regional_entry"]:
            print(row["address"],row["instruction"])
        print("Plan:",a.output)
        print("READ ONLY: native menu/purchase behavior unchanged.")
    except (ValueError,OSError,KeyError,ImportError) as e:
        p.exit(1,f"Dealership preparation rejected: {e}\n")


if __name__=="__main__":
    main()
