# M_DecalBounds_Test — recovered projection equations

Ground truth: `5020.asm` (PCD3D_SM5 pixel shader) and
`constant-buffer-map.json` (the material's own `UniformPreshaderFields`).
No fitted coefficients are used in this document.

## Inputs

- `p`: object-local position sampled from `LocalBounds` (`t2`).
- `n`: object-local normal sampled from `LocalNormal` (`t4`).
- `position = (PositionX, PositionY)` from the material instance.
- `yaw`, `pitch`, `roll`: material parameters `Yaw`, `PitchDown`, `Roll`.
  These parameters are turns, not degrees or radians: the preshader multiplies
  them by `2π`.
- `s = 255 * TextureScale`.
- `stretch = Stretch`.
- `flipSign = 1 - 2*Flip`.
- `uvChannel = DecalUVChannel` (0, 1, 2, or 3 in the shader's selector chain).

`LocalBounds` is the capture pass's object-local position, so its units are UE
object-space units (cm), not UV coordinates or a fitted per-mille range. The
same units apply directly to `PositionX/Y`. The final `ScaleUVsByCenter`
operation retains the engine function's literal `0.5` terms; they are not to be
removed as "rounding".

## Yaw/pitch basis

For the primary projection:

```
a = 2π * (pitch + 0.25) / 2
q = (cos(2π*yaw)*cos(a), sin(2π*yaw)*cos(a), sin(a))
R(p) = 2*q*dot(q, p) - dot(q, q)*p
```

This is the exact simplification of shader instructions 35–46. The material's
`MultiplyVectorWithQuaternion` input has scalar component zero; therefore the
cross-product coefficient in `cb2[2].x` is zero and the expression reduces as
above. Since `q` is unit length up to floating-point rounding, this is also
`2*q*dot(q,p) - p`.

The culling direction is a different vector (no quarter-turn offset):

```
c = (cos(2π*yaw)*cos(2π*pitch),
     sin(2π*yaw)*cos(2π*pitch),
     sin(2π*pitch))
```

## Primary decal UV

```
t = 2π * (-yaw - 0.25)
A = mat2((cos(t), -sin(t)),
         (sin(t),  cos(t)))       // rows used by the shader

b = 2π * roll
B = mat2((cos(b), -sin(b)),
         (sin(b),  cos(b)))       // rows used by the shader

v = B * (A * R(p).xy + (-PositionX, PositionY))
d = (s*stretch, s*flipSign)
uv = (v - 0.5) / d + 0.5
```

The matrix notation above uses row vectors in the same order as the two shader
`dp2` calls; equivalently:

```
r = R(p).xy
u0 = cos(t)*r.x - sin(t)*r.y - PositionX
u1 = sin(t)*r.x + cos(t)*r.y + PositionY
v0 = cos(b)*u0 - sin(b)*u1
v1 = sin(b)*u0 + cos(b)*u1
uv.x = (v0 - 0.5)/(s*stretch) + 0.5
uv.y = (v1 - 0.5)/(s*(1-2*Flip)) + 0.5
```

That expanded form is the implementation contract. It maps directly to
`5020.asm` instructions 47–57.

## Mirrored decal UV

The mirror is a second projection, not a texture-only horizontal flip:

```
qMirror = q with yaw replaced by -yaw
RMirror(p) = 2*qMirror*dot(qMirror,p) - dot(qMirror,qMirror)*p
tMirror = 2π * (yaw - 0.25)
bMirror = -2π * roll
positionMirror = (-PositionX - 1, PositionY)
```

Apply the same two 2D rotations and `ScaleUVsByCenter`, but use denominator
`(-s*stretch, s*flipSign)`. The mirror uses its own culling direction, also
computed with `-yaw` and no quarter-turn offset. The shader blends primary and
mirror outputs only when `Mirror != 0`.

## Bounds and culling

The texture's edge coverage is:

```
edge(u) = saturate((1 - 2*abs(u - 0.5)) * 100000)
coverage = edge(uv.x) * edge(uv.y) * sampledTexture.a
```

For the primary projection, the two factors deliberately use different inputs:

```
positionFacing = saturate(dot(p, c))
normalFacing = saturate(dot(n, c))
oppositeFactor = 1 + OppositeCull * (positionFacing - 1)
backFactor = 1 + BackFaceCull * (normalFacing - 1)
mask = round_pi_sat(oppositeFactor * backFactor)
```

The first `dp3_sat` reads the `LocalBounds` position register, not the normal;
this is easy to misread because both factors share `cb2[8]`. The mirrored pass
uses its normal for both factors. `round_pi_sat` is kept named here rather than
replaced with an assumed GLSL rounding function.

## Preshader constants used by the formulas

- `cb2[0].x = DecalUVChannel`
- `cb2[0].y = max(DecalUVChannel - 1, 0)`
- `cb2[0].z = max(DecalUVChannel - 2, 0)`
- `cb2[1].xyz = q`; `cb2[1].w = -dot(q,q)`
- `cb2[2].x = 0` (twice the quaternion scalar component)
- `cb2[2].yz = (cos(t), -sin(t))`
- `cb2[3].xy = (sin(t), cos(t))`
- `cb2[3].zw = (-PositionX, PositionY)`
- `cb2[4].xy = (cos(b), -sin(b))`
- `cb2[4].zw = (sin(b), cos(b))`
- `cb2[5].xy = (PositionX, -PositionY)` (unused by the placement path)
- `cb2[5].z = 255*TextureScale`; `cb2[5].w = Stretch`
- `cb2[6].x = 1 - 2*Flip`; `cb2[6].y = IsAlphaOnlyTexture`
- `cb2[7].rgb = Color.rgb`; `cb2[7].w = Highlight`
- `cb2[8].xyz = c`; `cb2[8].w = OppositeCull`
- `cb2[9].x = BackFaceCull`; `cb2[9].y = Color.a`
- `cb2[10..15]`: corresponding mirrored rotation, position, roll and culling
  constants, with the yaw/roll/sign changes listed above
- `cb2[15].w = Mirror`
- `cb2[16].rgb = TintColor.rgb`
- `cb2[17].rgb = SelectionColor.rgb`; `cb2[17].w = TintColor.a`

The full RPN provenance for every field is in `constant-buffer-map.json`.
