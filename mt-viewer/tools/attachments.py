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
