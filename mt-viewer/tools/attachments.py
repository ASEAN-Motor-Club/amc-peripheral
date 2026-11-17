"""Motor Town vehicle attachment transform conversion.

Owned configs use VectorValues[0..2] for position, Euler rotation and scale.
Workshop JSON uses the same fields with lower-case names and index-keyed objects.
All output transforms are glTF metres/Y-up, ready for the vehicle viewer.
"""
from tools.apply_sockets import rotator_quat
from tools.mk_manifest import ue_to_gltf_quat


def indexed(values, index, default=None):
    if isinstance(values, dict):
        return values.get(str(index), values.get(index, default))
    if isinstance(values, list) and len(values) > index:
        return values[index]
    return default


def xyz(value, default=0.0):
    if not isinstance(value, dict):
        return (default, default, default)
    return tuple(float(value.get(k, value.get(k.lower(), default))) for k in ('X', 'Y', 'Z'))


def convert(position, rotation, scale=None):
    x, y, z = xyz(position)
    if isinstance(rotation, dict) and any(k in rotation for k in ('Roll', 'Pitch', 'Yaw', 'roll', 'pitch', 'yaw')):
        roll = float(rotation.get('Roll', rotation.get('roll', 0.0)))
        pitch = float(rotation.get('Pitch', rotation.get('pitch', 0.0)))
        yaw = float(rotation.get('Yaw', rotation.get('yaw', 0.0)))
    else:
        roll, pitch, yaw = xyz(rotation)
    # Preserve source scale verbatim: some owned configs intentionally contain
    # zero-scale axes (hidden attachments); normalising them would make them visible.
    sx, sy, sz = xyz(scale, 1.0) if scale is not None else (1.0, 1.0, 1.0)
    return {
        'position': [x / 100.0, z / 100.0, -y / 100.0],
        'rotation': list(ue_to_gltf_quat(rotator_quat(pitch, yaw, roll))),
        'scale': [sx, sz, sy],
    }


def actor_root_rotation(lights):
    """Preserve authored bases for bidirectional lights that point outward.

    Other attachment meshes retain the catalogue's 180-degree glTF basis
    correction. The outward-pair rule is derived from component positions and
    rotations, not vehicle or item IDs.
    """
    if len(lights) >= 2:
        outward = []
        for light in lights:
            x, y, z, w = light['rotation']
            direction_x = 1.0 - 2.0 * (y * y + z * z)
            position_x = light['position'][0]
            outward.append(abs(direction_x) > 0.99 and direction_x * position_x > 0.001)
        if all(outward):
            return [0.0, 0.0, 0.0, 1.0]
    return [0.0, 1.0, 0.0, 0.0]


def attachment_to_part(record):
    vectors = record.get('vectors', record.get('VectorValues', []))
    strings = record.get('strings', record.get('StringValues', []))
    part = {
        'key': indexed(strings, 0, ''),
        'slot': str(record.get('slot', record.get('Slot', ''))),
        **convert(indexed(vectors, 0), indexed(vectors, 1), indexed(vectors, 2)),
    }
    return part


def component_to_part(component):
    props = component.get('Properties', {})
    return convert(props.get('RelativeLocation'), props.get('RelativeRotation'),
                   props.get('RelativeScale3D'))


def rect_light_to_part(component):
    props = component.get('Properties', {})
    color = props.get('LightColor', {})
    # RectLightComponent.LightColor is FColor (bytes), unlike the separate
    # MTLightControlComponent.Net_LightColor float property used by the mesh.
    rgb = [float(color.get(k, 0.0)) / 255.0 for k in ('R', 'G', 'B')]
    width = float(props.get('SourceWidth', 0.0)) / 100.0
    height = float(props.get('SourceHeight', 0.0)) / 100.0
    intensity = component.get('IntensityNits')
    if intensity is None or width <= 0.0 or height <= 0.0:
        raise ValueError('RectLight requires cooked IntensityNits and non-zero source dimensions')
    return {
        'type': 'rect',
        **convert(props.get('RelativeLocation'), props.get('RelativeRotation')),
        'color': rgb,
        'intensity': float(intensity),
        'width': width,
        'height': height,
        'attenuationRadius': float(props.get('AttenuationRadius', 0.0)) / 100.0,
        'barnDoorAngle': float(props.get('BarnDoorAngle', 0.0)),
        'castShadows': bool(props.get('CastShadows', False)),
    }


def spot_light_to_part(component):
    props = component.get('Properties', {})
    color = props.get('LightColor', {})
    rgb = [float(color.get(k, 255.0)) / 255.0 for k in ('R', 'G', 'B')]
    outer = float(props.get('OuterConeAngle', 35.0))
    inner = float(props.get('InnerConeAngle', outer))
    source_intensity = float(props.get('Intensity', 0.0))
    if props.get('IntensityUnits') == 'ELightUnits::Lumens':
        # Three.js SpotLight intensity is candela. Unreal's lumens are distributed
        # over the spotlight cone, not treated as nits or candela verbatim.
        import math
        solid_angle = 2.0 * math.pi * (1.0 - math.cos(math.radians(outer)))
        intensity = source_intensity / solid_angle if solid_angle > 0.0 else source_intensity / (4.0 * math.pi)
    else:
        intensity = source_intensity
    return {
        'type': 'spot',
        **convert(props.get('RelativeLocation'), props.get('RelativeRotation')),
        'color': rgb,
        'intensity': intensity,
        'sourceIntensity': source_intensity,
        'intensityUnits': props.get('IntensityUnits'),
        'outerConeAngle': outer,
        'innerConeAngle': inner,
        'attenuationRadius': float(props.get('AttenuationRadius', 0.0)) / 100.0,
        'castShadows': bool(props.get('CastShadows', False)),
    }
