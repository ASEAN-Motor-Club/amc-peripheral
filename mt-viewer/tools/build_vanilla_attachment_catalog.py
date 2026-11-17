#!/usr/bin/env python3
"""Build the vanilla light/oversize attachment catalogue from CUE actor dumps.

Inputs are the actor text dumps, mtglb exports and mtmats sidecar. Existing LED
actors are preserved. Component-local transforms and material overrides stay
attached to their source component; no socket or vehicle transform is applied.
"""
import argparse
import json
import math
import shutil
from pathlib import Path

from tools.attachments import component_to_part, spot_light_to_part, yaw_rotate_part

LIGHT_ACTORS = {
    **{f'Attachment_Light_{i:02d}': f'Light_{i:02d}' for i in range(1, 9)},
    'Attachment_Light_09': 'Light_09_Blinker',
    'Attachment_Light_10': 'Light_10_Blinker',
    'Attachment_Light_11': 'Light_11_Blinker',
    'Attachment_Light_12': 'Light_12_Blinker',
    'Attachment_Light_13': 'Light_13',
    'Attachment_Light_14': 'Light_14_SideMarker',
    'Attachment_Light_15': 'Light_15_Blinker',
}
SIGN_ACTORS = {
    'Attachment_OversizeLoad_PanelSign_Left': 'OversizeLoad_PanelSign_Left',
    'Attachment_OversizeLoad_PanelSign_Right': 'OversizeLoad_PanelSign_Right',
    **{f'Attachment_OversizeLoad_Sign_{i}': f'OversizeLoad_Sign_{i}' for i in range(1, 8)},
}
ACTORS = {**LIGHT_ACTORS, **SIGN_ACTORS}


def blocks(path):
    text = path.read_text()
    pos = 0
    while True:
        heading_start = text.find('=== U', pos)
        if heading_start < 0:
            return
        start = text.find('\n', heading_start) + 1
        obj, end = json.JSONDecoder().raw_decode(text[start:])
        yield text[heading_start:start - 1], obj
        pos = start + end


def material_def(raw):
    colors = raw.get('colors', {})
    color = colors.get('Color', colors.get('Light Color', [1.0, 1.0, 1.0, 1.0]))
    scalars = raw.get('scalars', {})
    result = {
        'slot': True,
        'baseColor': color[:3],
        'materialName': raw.get('materialName'),
        'material': raw.get('material'),
        'metalness': float(scalars.get('Metallic', 0.0)),
        'roughness': float(scalars.get('Roughness', 0.55)),
    }
    if raw.get('diffusePng'):
        result['map'] = '/vehicles/attachments/textures/' + Path(raw['diffusePng']).name
    if raw.get('translucent'):
        result['alphaMode'] = 'BLEND'
        result['opacity'] = float(scalars.get('Opacity', 0.5))
    elif raw.get('masked'):
        result['alphaMode'] = 'MASK'
    return result


def material_key(package_path):
    return package_path.rsplit('/', 1)[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--actors', type=Path, required=True)
    parser.add_argument('--exports', type=Path, required=True)
    parser.add_argument('--materials', type=Path, required=True, help='Directory containing mesh_materials.json and tex/')
    parser.add_argument('--site', type=Path, required=True)
    args = parser.parse_args()

    sidecar = json.loads((args.materials / 'mesh_materials.json').read_text())
    extra_materials = sidecar.get('__materials__', {})
    attachments = args.site / 'attachments'
    glb_dir = attachments / 'glb'
    texture_dir = attachments / 'textures'
    glb_dir.mkdir(parents=True, exist_ok=True)
    texture_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = attachments / 'catalog.json'
    materials_path = attachments / 'materials.json'
    catalog = json.loads(catalog_path.read_text())
    material_table = json.loads(materials_path.read_text())
    material_table.setdefault('materialsByMesh', {})
    material_table.setdefault('slotsByMesh', {})

    for key, actor_name in ACTORS.items():
        source_name = '_Base_RotatingLight_01' if key == 'Attachment_Light_06' else actor_name
        source = args.actors / f'{source_name}.json'
        components = []
        lights = []
        used_meshes = set()
        for heading, obj in blocks(source):
            if heading.startswith('=== UStaticMeshComponent'):
                props = obj.get('Properties', {})
                ref = props.get('StaticMesh', {}).get('ObjectPath')
                if not ref:
                    continue
                mesh = ref.rsplit('/', 1)[-1].rsplit('.', 1)[0]
                used_meshes.add(mesh)
                component = {'mesh': mesh, **component_to_part(obj)}
                overrides = []
                for material in props.get('OverrideMaterials', []):
                    if material and material.get('ObjectPath'):
                        package = material['ObjectPath'].rsplit('.', 1)[0].replace('MotorTown/Content/', 'Game/', 1)
                        overrides.append(material_key(package))
                if overrides:
                    component['materialSlots'] = overrides
                components.append(component)
            elif heading.startswith('=== USpotLightComponent'):
                lights.append(spot_light_to_part(obj))
        if not components:
            raise RuntimeError(f'{key}: no mesh components in {source}')

        if key.startswith('Attachment_OversizeLoad_Sign_'):
            # Rear-sign meshes are authored with the printed face toward +X.
            # Rear attachments must present that face toward -X, away from the vehicle.
            components = [yaw_rotate_part(component, 180) for component in components]
            lights = [yaw_rotate_part(light, 180) for light in lights]

        first_mesh = components[0]['mesh']
        color = lights[0]['color'] if lights else [1.0, 1.0, 1.0]
        catalog['actors'][key] = {
            'mesh': first_mesh,
            'color': color,
            'sourceActor': source_name.lower(),
            'components': components,
            'lights': lights,
        }
        for mesh in used_meshes:
            source_glb = args.exports / mesh / f'{mesh}.glb'
            if not source_glb.is_file() or source_glb.stat().st_size == 0:
                raise FileNotFoundError(source_glb)
            shutil.copy2(source_glb, glb_dir / source_glb.name)
            raw_slots = sidecar[mesh]
            defs = {slot['slot']: material_def(slot) for slot in raw_slots}
            material_table['slotsByMesh'][mesh] = [slot['slot'] for slot in raw_slots]
            material_table['materialsByMesh'][mesh] = defs

        for component in components:
            mesh = component['mesh']
            defs = material_table['materialsByMesh'][mesh]
            for override in component.get('materialSlots', []):
                if override in defs:
                    continue
                package = next((p for p in extra_materials if material_key(p) == override), None)
                if package is None:
                    raise KeyError(f'{key}: no extracted override material {override}')
                defs[override] = material_def(extra_materials[package])

    for texture in (args.materials / 'tex').glob('*.png'):
        shutil.copy2(texture, texture_dir / texture.name)
    catalog['actors'] = dict(sorted(catalog['actors'].items()))
    catalog['version'] = 3
    material_table['version'] = 2
    catalog_path.write_text(json.dumps(catalog, indent=1) + '\n')
    materials_path.write_text(json.dumps(material_table, indent=1) + '\n')
    print(f'catalogued {len(ACTORS)} actors; total actors={len(catalog["actors"])}')
    print(f'meshes={len(material_table["materialsByMesh"])} textures={len(list(texture_dir.glob("*.png")))}')


if __name__ == '__main__':
    main()
