"""Exact CPU form of Motor Town's recovered decal projection (shader 5020).

Angles are turns. Positions and the object-local point are UE object-space
units. The formulas intentionally retain the engine's literal 0.5 terms.
"""

import math

TAU = 2.0 * math.pi


def rotation_axis(yaw, pitch):
    """Return the scalar-zero quaternion's vector part from the preshader."""
    a = TAU * (pitch + 0.25) / 2.0
    return (
        math.cos(TAU*yaw) * math.cos(a),
        math.sin(TAU*yaw) * math.cos(a),
        math.sin(a),
    )


def rotate_local(point, yaw, pitch):
    """Simplification of shader 5020 instructions 35-46."""
    q = rotation_axis(yaw, pitch)
    q_dot_p = sum(a*b for a, b in zip(q, point))
    q_dot_q = sum(a*a for a in q)
    return tuple(2.0*a*q_dot_p - q_dot_q*b for a, b in zip(q, point))


def primary_uv(point, position, yaw, pitch, roll, texture_scale,
               stretch=1.0, flip=0.0):
    """Return the primary decal texture UV for an object-local position."""
    rx, ry = rotate_local(point, yaw, pitch)[:2]
    t = TAU * (-yaw - 0.25)
    x = math.cos(t)*rx - math.sin(t)*ry - position[0]
    y = math.sin(t)*rx + math.cos(t)*ry + position[1]
    b = TAU * roll
    u = math.cos(b)*x - math.sin(b)*y
    v = math.sin(b)*x + math.cos(b)*y
    scale = 255.0 * texture_scale
    return (
        (u - 0.5)/(scale*stretch) + 0.5,
        (v - 0.5)/(scale*(1.0-2.0*flip)) + 0.5,
    )


def mirror_uv(point, position, yaw, pitch, roll, texture_scale,
              stretch=1.0, flip=0.0):
    """Return the shader's independent mirrored-projection UV."""
    return primary_uv(
        point,
        (position[0]+1.0, position[1]),
        -yaw,
        pitch,
        -roll,
        texture_scale,
        -stretch,
        flip,
    )
