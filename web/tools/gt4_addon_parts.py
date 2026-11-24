#!/usr/bin/env python3
"""Lossless field preview of NFSU2 Binary DBModelParts exports.

Format reference: Nikki (MIT), Underground2 DBModelPart, CPStruct and
attributes, and Core/Map.cs:
https://github.com/nlgxzef/Darius/tree/master/Nikki/Support.Underground2
No native database writes: JSON is an intermediate representation, not an
installable game file. Unknown encodings are rejected rather than guessed.
"""
import struct

GROUPS = {
    1: "STOCK REMAP ONLINE CENTER MIRROR ISDECAL FULLBODY HOODLEFT HOODRIGHT VERTSPLIT WHEELLEFT WHEELRIGHT USEMARKER1 USEMARKER2 COMPLEXTARGET UNPAINTABLE CARBONFIBRE EXCLUDE_SUV EXCLUDE_UG1 EXCLUDE_UG2 WARNONDELETE KITNOTPAINT01 KITNOTPAINT03 KITNOTPAINT04 KITNOTPAINT06 KITNOTPAINT07 KITNOTPAINT10 KITNOTPAINT18 STOCK_MATERIAL",
    2: "RED RED2 BLUE ALPHA GREEN GLOSS BLUE2 ALPHA2 GREEN2 MAX_LOD DISPRED DISPBLUE HUDINDEX ANIMSTYLE DISPGREEN KITNUMBER NUMCOLOURS NUM_DECALS WIDEBODYKIT DAMAGELEVEL SPOKE_COUNT INNER_RADIUS OUTER_RADIUS LANGUAGEHASHABR NUMREMAPCOLOURS MORPHTARGET_NUM PART_NAME_SELECTOR LOD_NAME_PREFIX_SELECTOR",
    3: "BLEND HOODHUE HOODLUM HOODSAT TIREHUE TIRELUM TIRESAT SPINNEROFFSET",
    4: "TEXTURE NAME_OFFSET LOD_CHARACTERS_OFFSET",
    8: "CV MAT0 MAT1 MAT2 MAT3 MAT4 MAT5 MAT6 MAT7 NAME SIZE SHAPE SWATCH MATNAMEA MATNAMEB HOODUNDER BRAND_NAME PAINTGROUP HOODEMITTER TEXTUREHASH EXCLUDEDECAL LANGUAGEHASH SPEECHCOLOUR TEXTURE_NAME WHEELEMITTER SPECIFICCARNAME SPINNER_TEXTURE GROUPLANGUAGEHASH VINYLLANGUAGEHASH COLOR0LANGUAGEHASH COLOR1LANGUAGEHASH COLOR2LANGUAGEHASH COLOR3LANGUAGEHASH LIGHT_MATERIAL_NAME PART_NAME_BASE_HASH LOD_NAME_PREFIX_NAMEHASH"
}


def hash_name(s):
    value = 0xffffffff
    for b in s.encode("ascii"):
        value = (33 * value + b) & 0xffffffff
    return value


KNOWN = {hash_name(name): (kind, name) for kind, names in GROUPS.items() for name in names.split()}
KNOWN[0x9A9B6DDC] = (3, "0x9A9B6DDC")


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError(f"truncated part export at {self.pos}")
        result = self.data[self.pos:self.pos+count]
        self.pos += count
        return result

    def number(self, count):
        return int.from_bytes(self.take(count), "little")

    def flag(self):
        value = self.number(1)
        if value not in (0, 1):
            raise ValueError(f"invalid Boolean at {self.pos-1}")
        return bool(value)

    def string(self):
        end = self.data.find(b"\0", self.pos, self.pos + 65537)
        if end == -1:
            raise ValueError(f"unterminated or oversized string at {self.pos}")
        return self.take(end-self.pos+1)[:-1].decode("utf-8")

    def optional_string(self):
        return self.string() if self.flag() else None

    def lod(self):
        if not self.flag():
            return None
        templated = self.flag()
        base = self.optional_string()
        flags = [self.flag() for _ in range(8)]
        return {"templated": templated, "concatenator": base,
                "geometry": [self.string() if flag else None for flag in flags]}

    def attribute(self):
        key = self.number(4)
        custom = key not in KNOWN
        if custom:
            name, kind = self.string(), self.number(4)
        else:
            kind, name = KNOWN[key]
        if kind == 1:
            value = self.flag()
        elif kind in (2, 3, 6):
            # Keep exact IEEE754 and integer/color bits, without NaN coercion.
            value = self.number(4)
        elif kind == 4:
            value = self.optional_string()
        elif kind == 5:
            flags = [self.flag(), self.flag()]
            value = [self.string() if flag else None for flag in flags]
        elif kind == 8:
            value = self.string()
        else:
            raise ValueError(f"unsupported attribute {key:#x} type {kind} at {self.pos}")
        return {"key": key, "name": name, "type": kind, "custom": custom, "value": value}


def parse_parts(data, expected_car):
    if not 0 < len(data) <= 16 * 1024 * 1024:
        raise ValueError("invalid part export size")
    r = Reader(data)
    car = r.string()
    count = r.number(4)
    if car != expected_car or not 0 < count <= 65535:
        raise ValueError("invalid DBModelParts car/count")
    parts = []
    for i in range(count):
        n = r.number(4)
        if n > 1024:
            raise ValueError(f"too many attributes in part {i}")
        part = {"label": r.string(), "debug_name": r.string(),
                "group": r.number(1), "upgrade_group": r.number(2),
                "lod": r.lod(), "attributes": [r.attribute() for _ in range(n)]}
        parts.append(part)
    if r.pos != len(data):
        raise ValueError(f"unexpected trailing DBModelParts bytes: {len(data)-r.pos}")
    return {"car": car, "count": count, "parts": parts}
