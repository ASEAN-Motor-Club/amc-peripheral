#!/usr/bin/env python3
"""glb_slots.py — make every glTF primitive carry its UE material-slot name.

CUE4Parse's glTF writer emits one material per unique UE material, ordered by its
own dedupe (Body.glb lists M_Palette first, M_Body second) — not in the mesh's
material-slot order. Two consequences if you leave it alone:

  * you cannot map primitive -> slot by index (the body gets the palette paint);
  * two slots that share one material asset (Body_01 + Seat_01 both on M_Body, or
    left/right tail light both on M_TailLight) collapse into a single material, so
    their different paint colours cannot be expressed at all.

So rewrite the GLB: one material entry per primitive, named after the slot it
occupies. Geometry/BIN is untouched — only the JSON chunk grows.
"""
import copy
import json
import struct

MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def _split_glb(data):
    magic, version, _ = struct.unpack("<III", data[:12])
    if magic != MAGIC:
        raise ValueError("not a GLB")
    chunks, off = [], 12
    while off < len(data):
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        body = data[off + 8:off + 8 + clen]
        chunks.append([ctype, body])
        off += 8 + clen
    return version, chunks


def _join_glb(version, chunks):
    out = [struct.pack("<III", MAGIC, version, 0)]
    for ctype, body in chunks:
        if ctype == JSON_CHUNK:
            pad = (4 - len(body) % 4) % 4
            body = body + b" " * pad
        else:
            pad = (4 - len(body) % 4) % 4
            body = body + b"\0" * pad
        out.append(struct.pack("<II", len(body), ctype))
        out.append(body)
    blob = b"".join(out)
    return blob[:8] + struct.pack("<I", len(blob)) + blob[12:]


def rewrite(src, dst, slots):
    """Name every primitive's material after its UE slot.

    `slots` is a list of (slotName, materialAssetName) in UE material-slot order.
    Primitives come out of CUE4Parse in SECTION order with a correct material
    reference, so match on that material name and take the next unused slot that
    owns it — never on primitive index (the orders differ: Boxy's Body.glb emits
    the palette section first, the body section second).
    """
    pairs = [(s, None) if isinstance(s, str) else (s[0], s[1]) for s in slots]
    data = open(src, "rb").read()
    version, chunks = _split_glb(data)
    ji = next(i for i, (t, _) in enumerate(chunks) if t == JSON_CHUNK)
    g = json.loads(chunks[ji][1].decode("utf-8"))

    old_mats = g.get("materials", [])
    new_mats, prim_i, used = [], 0, {}

    for mesh in g.get("meshes", []):
        for prim in mesh.get("primitives", []):
            orig = old_mats[prim.get("material", 0)] if old_mats else {}
            asset = (orig.get("name") or "").split(".")[0]

            slot = None
            for cand, matname in pairs:
                if matname and asset and matname.split(".")[0] == asset and cand not in used:
                    slot = cand
                    break
            if slot is None:
                for cand, _ in pairs:
                    if cand not in used:
                        slot = cand
                        break
            if slot is None and prim_i < len(pairs):
                slot = pairs[prim_i][0]

            mat = copy.deepcopy(orig)
            if slot:
                used[slot] = True
                mat["name"] = slot
            prim["material"] = len(new_mats)
            new_mats.append(mat)
            prim_i += 1

    if new_mats:
        g["materials"] = new_mats
    chunks[ji][1] = json.dumps(g, separators=(",", ":")).encode("utf-8")
    open(dst, "wb").write(_join_glb(version, chunks))
    return prim_i, len(new_mats)


if __name__ == "__main__":
    import sys
    src, dst = sys.argv[1], sys.argv[2]
    slots = json.loads(sys.argv[3])
    print(rewrite(src, dst, slots))
