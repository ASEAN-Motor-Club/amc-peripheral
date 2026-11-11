#!/usr/bin/env python3
"""bake_materials.py — build the viewer's material table from the extractor output.

Data sources (both produced on the host by the CUE4Parse tools):

  <build>/mesh_materials.json   per-mesh slot table from `mtmats`
                                (CUE4Parse CMaterialParams2 = material-GRAPH params:
                                 diffuse/roughness/metallic/normal/emissive texture
                                 refs, vector params, scalars, blend mode)
  <build>/tex/*.png             those textures already decoded to PNG
  <build>/<Part>/*.glb          geometry; material slots carry only names

CMaterialParams2 is the important one: the glTF exporter only reports *named*
texture parameters, so a material whose base colour hangs off an unnamed
TextureSample node exports empty and renders white (car wheels were exactly that).

Output: <site>/materials.json  {materialName: three.js material params}
        <site>/textures/*.png  deduplicated copies
        <site>/glb/*.glb

Data facts that are NOT rendering bugs:
  * M_Body has Color #FFFFFF + Metallic .3 + Roughness .5 and no diffuse texture —
    the game tints the body at the paint shop, so a stock body is white.
  * M_Palette carries the paint/livery atlas (Palette_PolygonCity_Texture_01_A).
  * Lamp materials expose only runtime scalars (HeadLight/BrakeLight = 0); the
    emissive colour here is a design choice, flagged "synthetic": "lamp".
  * M_Mirror's only texture is UE4_LOGO_CARD — a placeholder card standing in for
    an in-game render target. Drawing it looks wrong, so mirrors get a metal
    finish instead, flagged "synthetic": "mirror".
"""
import hashlib
import json
import os
import shutil
import sys

LAMPS = {
    "M_HeadLight": ([1.0, 0.96, 0.86], 1.1),
    "M_TailLight": ([1.0, 0.12, 0.10], 0.9),
    "M_TurnSignalLight": ([1.0, 0.55, 0.10], 0.8),
    "M_ReverseLight": ([1.0, 1.0, 1.0], 0.7),
    "M_SideMarkerLight": ([1.0, 0.72, 0.30], 0.6),
}
TEX_SKIP = ("RT_LayerPreview", "RT_ActivePreview", "ActiveLayerCRT2D",
            "PM_Normals", "PM_Emissive", "UE4_LOGO_CARD")


def pick_texture(tex, prefer):
    for key in prefer:
        if key in tex:
            return tex[key]
    return None


def first_containing(tex, needle):
    for k, v in tex.items():
        if needle in k and not any(s in k for s in TEX_SKIP):
            return v
    return None


def main(build_dir, out_dir):
    mm_path = os.path.join(build_dir, "mesh_materials.json")
    if not os.path.exists(mm_path):
        sys.exit(f"missing {mm_path} — run the mtmats step first")
    mm = json.load(open(mm_path))

    tex_dir = os.path.join(out_dir, "textures")
    glb_dir = os.path.join(out_dir, "glb")
    os.makedirs(tex_dir, exist_ok=True)
    os.makedirs(glb_dir, exist_ok=True)
    by_sha = {}

    def publish(rel):
        if not rel:
            return None
        src = os.path.join(build_dir, rel)
        if not os.path.exists(src):
            return None
        data = open(src, "rb").read()
        sha = hashlib.sha1(data).hexdigest()[:16]
        if sha not in by_sha:
            with open(os.path.join(tex_dir, sha + ".png"), "wb") as f:
                f.write(data)
            by_sha[sha] = ("textures/" + sha + ".png", len(data))
        return by_sha[sha][0]

    mats, conflicts = {}, []
    for mesh, slots in mm.items():
        for slot in slots:
            full = slot.get("material", "")
            name = os.path.basename(full).split(".")[0] or full
            tex = slot.get("textures") or {}
            cols = slot.get("colors") or {}
            scal = slot.get("scalars") or {}

            entry = {
                "material": full,
                "blendMode": slot.get("blendMode"),
                "baseColor": [1.0, 1.0, 1.0],
                "metalness": round(float(scal.get("Metallic", 0.0)), 4),
                "roughness": round(float(scal.get("Roughness", 0.6)), 4),
                "alphaMode": "BLEND" if slot.get("translucent") else ("MASK" if slot.get("masked") else "OPAQUE"),
                "doubleSided": bool(slot.get("translucent")),
            }
            if "Color" in cols:
                c = cols["Color"]
                entry["baseColor"] = [round(c[0], 4), round(c[1], 4), round(c[2], 4)]

            diffuse = slot.get("diffusePng") or pick_texture(
                tex, ["PM_Diffuse", "Base Color Texture", "Diffuse"]) or first_containing(tex, "Texture_01_A")
            if diffuse:
                entry["map"] = publish(diffuse)
            rough = pick_texture(tex, ["PM_Roughness"]) or first_containing(tex, "Roughness")
            if rough:
                entry["roughnessMap"] = publish(rough)
            metal = pick_texture(tex, ["PM_Metalness"]) or first_containing(tex, "Metallic")
            if metal:
                entry["metalnessMap"] = publish(metal)
            norm = pick_texture(tex, ["PM_Normals"]) or first_containing(tex, "Normal")
            if norm:
                entry["normalMap"] = publish(norm)

            if entry["alphaMode"] == "BLEND":
                entry["opacity"] = round(float(scal.get("Opacity", 0.35)), 4)
                entry["depthWrite"] = False

            if name in LAMPS:
                colour, strength = LAMPS[name]
                entry.update({"emissive": colour, "emissiveIntensity": strength,
                              "metalness": 0.0, "roughness": 0.35, "map": None,
                              "synthetic": "lamp"})

            if name == "M_Mirror":
                entry.update({"map": None, "metalness": 0.95, "roughness": 0.08,
                              "baseColor": [0.72, 0.76, 0.80], "synthetic": "mirror"})

            # Nothing at all resolved for this material (no map, no colour params, no
            # scalars): render it as neutral dark plastic instead of blowing out to
            # white, and say so in the table.
            if not entry.get("map") and not cols and not scal and name not in LAMPS:
                entry.update({"baseColor": [0.30, 0.30, 0.32], "roughness": 0.65,
                              "metalness": 0.0, "synthetic": "no-data"})

            if name in mats and {k: v for k, v in mats[name].items() if k != "material"} != \
                               {k: v for k, v in entry.items() if k != "material"}:
                conflicts.append(name)
            mats[name] = entry

    for part in sorted(os.listdir(build_dir)):
        pdir = os.path.join(build_dir, part)
        if not os.path.isdir(pdir):
            continue
        for root, _, files in os.walk(pdir):
            for f in files:
                if f.lower().endswith(".glb"):
                    shutil.copy2(os.path.join(root, f), os.path.join(glb_dir, f))

    table = {
        "format": 2,
        "materials": mats,
        "textures": {sha: {"uri": rel, "bytes": size} for sha, (rel, size) in sorted(by_sha.items())},
    }
    json.dump(table, open(os.path.join(out_dir, "materials.json"), "w"), indent=1)

    withmap = sorted(n for n, m in mats.items() if m.get("map"))
    print(f"materials: {len(mats)}  with diffuse map: {len(withmap)}  "
          f"textures: {len(by_sha)} ({sum(s for _, s in by_sha.values()) // 1024} KB)")
    if withmap:
        print("  textured:", ", ".join(withmap))
    missing = sorted(n for n, m in mats.items() if m.get("mapMissing"))
    if missing:
        print("  missing texture files:", ", ".join(missing))
    if conflicts:
        print("  conflicting defs:", ", ".join(sorted(set(conflicts))))
    return table


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: bake_materials.py <build_dir> <out_dir>")
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
