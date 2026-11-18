// Motor Town decal projection recovered from M_DecalBounds_Test shader 5020.
// Angles are turns; positions are object-local UE units. No fitted constants.

const TAU = 2 * Math.PI;

export function decalFallbackSlots(decalSlots, slotDefs, bodyVariants, selectedIndex) {
  if (decalSlots.length) return new Set();
  // A saved bodyMaterialIndex can outlive the vehicle's BodyMaterialList (item 99433
  // requests index 16 for Zino, which no longer exists). That must not disable decals:
  // fall through to the conservative Body/Shell/Palette slots instead of returning empty.
  // Without BodyMaterialList metadata, Body/Shell and Palette are the body slots.
  // Do NOT include PolygonCityPallete / Mat_PolygonCity_Texture*: on Vista those are
  // the four wheel meshes (Vista_L/Vista_R at the corners), so adding them painted
  // decals onto tyres.
  return new Set(Object.keys(slotDefs || {}).filter(slot =>
    /^(Body|Shell|Palette)/i.test(slot)
  ));
}

// Some vehicle assets use a differently named material slot for the painted
// body panels (Nuke's outer skin is `Seats_01` in the exported glTF, while its
// CDO only labels `Body_01`). Any slot driven by the generic body shader is a
// body panel, so include it alongside the CDO's explicit receiver names.
export function decalReceiverSlots(decalSlots, slotDefs, slotExtents = {}) {
  const out = new Set(decalSlots || []);
  const bodySlots = Object.entries(slotDefs || {}).filter(([, def]) => {
    const material = `${def?.materialName || ""} ${def?.material || ""}`;
    return /(^|[\/\s])M_Body([\/.\s]|$)/i.test(material);
  });
  const maxExtent = Math.max(0, ...bodySlots.map(([slot]) => slotExtents[slot] || 0));
  if (!maxExtent) return out;
  // Body panels are the largest M_Body slots. A fixed 1.5x margin missed cars
  // whose shell is split across two similarly-sized slots (Raton Body/Body_0)
  // but still excludes seats and other small M_Body trim.
  for (const [slot] of bodySlots) {
    if ((slotExtents[slot] || 0) >= maxExtent * 0.6) out.add(slot);
  }
  return out;
}

export function decalAtlasUv(layerIndex, q) {
  const col = layerIndex % 8;
  const row = Math.floor(layerIndex / 8);
  // Projection q is correct. Only the image V convention is inverted between
  // the game textures and the top-to-bottom canvas atlas (flipY=true).
  return [(col + q[0]) / 8, ((7 - row) + (1 - q[1])) / 8];
}

function axis(yaw, pitch) {
  const a = TAU * (pitch + 0.25) / 2;
  return [Math.cos(TAU*yaw)*Math.cos(a), Math.sin(TAU*yaw)*Math.cos(a), Math.sin(a)];
}

function rotate(point, yaw, pitch) {
  const q = axis(yaw, pitch);
  const dp = q[0]*point[0] + q[1]*point[1] + q[2]*point[2];
  const qq = q[0]*q[0] + q[1]*q[1] + q[2]*q[2];
  return q.map((x, i) => 2*x*dp - qq*point[i]);
}

function projectUv(point, position, yaw, pitch, roll, textureScale, stretch=1, flip=0) {
  const r = rotate(point, yaw, pitch);
  const t = TAU * (-yaw - 0.25);
  const x = Math.cos(t)*r[0] - Math.sin(t)*r[1] - position[0];
  const y = Math.sin(t)*r[0] + Math.cos(t)*r[1] + position[1];
  const b = TAU * roll;
  const u = Math.cos(b)*x - Math.sin(b)*y;
  const v = Math.sin(b)*x + Math.cos(b)*y;
  const s = 255 * textureScale;
  return [(u-0.5)/(s*stretch)+0.5, (v-0.5)/(s*(1-2*flip))+0.5];
}

export function primaryUv(point, position, yaw, pitch, roll, textureScale, stretch=1, flip=0) {
  // Saved workshop primary layers use the opposite yaw from shader 5020.
  return projectUv(point, position, -yaw, pitch, roll, textureScale, stretch, flip);
}

export function mirrorUv(point, position, yaw, pitch, roll, textureScale, stretch=1, flip=0) {
  // Mirror projection keeps workshop yaw; mirror culling independently negates it.
  return projectUv(point, [-position[0]-1, position[1]], yaw, pitch, -roll,
    textureScale, -stretch, flip);
}

function visibility(point, normal, yaw, pitch, flags, mirrored) {
  const cy = Math.cos(TAU * (mirrored ? -yaw : yaw));
  const sy = Math.sin(TAU * (mirrored ? -yaw : yaw));
  const cp = Math.cos(TAU * pitch);
  const sp = Math.sin(TAU * pitch);
  const c = [cy*cp, sy*cp, sp];
  const dp = c[0]*point[0] + c[1]*point[1] + c[2]*point[2];
  const dn = c[0]*normal[0] + c[1]*normal[1] + c[2]*normal[2];
  const opposite = (flags & 4) ? 1 : 0;
  const backface = (flags & 8) ? 1 : 0;
  return (1 + opposite*(Math.max(0, Math.min(1, dn))-1))
       * (1 + backface*(Math.max(0, Math.min(1, dn))-1));
}

export function primaryVisibility(point, normal, yaw, pitch, flags) {
  return visibility(point, normal, yaw, pitch, flags, false);
}

export function mirrorVisibility(point, normal, yaw, pitch, flags) {
  return visibility(point, normal, yaw, pitch, flags, true);
}

export const DECAL_PROJECTION_GLSL = /* glsl */`
vec3 mtDecalAxis(float yaw, float pitch) {
  float a = 6.283185307179586 * (pitch + 0.25) / 2.0;
  return vec3(cos(6.283185307179586*yaw)*cos(a),
              sin(6.283185307179586*yaw)*cos(a), sin(a));
}
vec3 mtDecalRotate(vec3 p, float yaw, float pitch) {
  vec3 q = mtDecalAxis(yaw, pitch);
  return 2.0*q*dot(q, p) - dot(q, q)*p;
}
vec2 mtDecalProjectUv(vec3 p, vec2 PositionXPositionY, vec3 turns,
                      float TextureScale, float Stretch, float Flip) {
  vec3 r = mtDecalRotate(p, turns.x, turns.y);
  float t = 6.283185307179586 * (-turns.x - 0.25);
  float x = cos(t)*r.x - sin(t)*r.y - PositionXPositionY.x;
  float y = sin(t)*r.x + cos(t)*r.y + PositionXPositionY.y;
  float b = 6.283185307179586 * turns.z;
  vec2 v = vec2(cos(b)*x - sin(b)*y, sin(b)*x + cos(b)*y);
  vec2 d = vec2(255.0*TextureScale*Stretch,
                255.0*TextureScale*(1.0-2.0*Flip));
  return (v - 0.5)/d + 0.5;
}
vec2 mtDecalPrimaryUv(vec3 p, vec2 PositionXPositionY, vec3 turns,
                      float TextureScale, float Stretch, float Flip) {
  return mtDecalProjectUv(p, PositionXPositionY,
    vec3(-turns.x, turns.y, turns.z), TextureScale, Stretch, Flip);
}
vec2 mtDecalMirrorUv(vec3 p, vec2 PositionXPositionY, vec3 turns,
                     float TextureScale, float Stretch, float Flip) {
  // Mirror projection keeps workshop yaw; mirror culling independently negates it.
  return mtDecalProjectUv(p, vec2(-PositionXPositionY.x-1.0, PositionXPositionY.y),
    vec3(turns.x, turns.y, -turns.z), TextureScale, -Stretch, Flip);
}
float mtDecalVisibility(vec3 p, vec3 n, vec3 turns, int flags, bool mirrored) {
  float yaw = mirrored ? -turns.x : turns.x;
  float cy = cos(6.283185307179586*yaw);
  float sy = sin(6.283185307179586*yaw);
  float cp = cos(6.283185307179586*turns.y);
  float sp = sin(6.283185307179586*turns.y);
  vec3 c = vec3(cy*cp, sy*cp, sp);
  float opposite = (flags & 4) != 0 ? 1.0 : 0.0;
  float backface = (flags & 8) != 0 ? 1.0 : 0.0;
  return (1.0 + opposite*(clamp(dot(n, c), 0.0, 1.0)-1.0))
       * (1.0 + backface*(clamp(dot(n, c), 0.0, 1.0)-1.0));
}
vec2 mtDecalAtlasUv(float col, float row, vec2 q) {
  return vec2((col+q.x)/8.0, ((7.0-row)+(1.0-q.y))/8.0);
}
float mtDecalEdge(float u) {
  return clamp((1.0 - 2.0*abs(u - 0.5))*100000.0, 0.0, 1.0);
}
`;
