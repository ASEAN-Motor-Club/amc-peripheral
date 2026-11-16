// Motor Town decal projection recovered from M_DecalBounds_Test shader 5020.
// Angles are turns; positions are object-local UE units. No fitted constants.

const TAU = 2 * Math.PI;

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

export function primaryUv(point, position, yaw, pitch, roll, textureScale, stretch=1, flip=0) {
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

export function mirrorUv(point, position, yaw, pitch, roll, textureScale, stretch=1, flip=0) {
  return primaryUv(point, [position[0]+1, position[1]], -yaw, pitch, -roll,
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
  return (1 + opposite*(Math.max(0, Math.min(1, dp))-1))
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
vec2 mtDecalPrimaryUv(vec3 p, vec2 PositionXPositionY, vec3 turns,
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
vec2 mtDecalMirrorUv(vec3 p, vec2 PositionXPositionY, vec3 turns,
                     float TextureScale, float Stretch, float Flip) {
  return mtDecalPrimaryUv(p, PositionXPositionY + vec2(1.0, 0.0),
    vec3(-turns.x, turns.y, -turns.z), TextureScale, -Stretch, Flip);
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
  return (1.0 + opposite*(clamp(dot(p, c), 0.0, 1.0)-1.0))
       * (1.0 + backface*(clamp(dot(n, c), 0.0, 1.0)-1.0));
}
float mtDecalEdge(float u) {
  return clamp((1.0 - 2.0*abs(u - 0.5))*100000.0, 0.0, 1.0);
}
`;
