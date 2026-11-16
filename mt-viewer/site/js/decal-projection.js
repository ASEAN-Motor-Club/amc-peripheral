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

export function decalPrecompute(rotationDegrees) {
  const [yaw, pitch, roll] = rotationDegrees.map(v => v / 360);
  const a = TAU * (pitch + 0.25) / 2, t = TAU * (-yaw - 0.25), b = TAU * roll;
  return {
    axis: [Math.cos(TAU*yaw)*Math.cos(a), Math.sin(TAU*yaw)*Math.cos(a), Math.sin(a)],
    trig: [Math.cos(t), Math.sin(t), Math.cos(b), Math.sin(b)],
    cull: [Math.cos(TAU*yaw)*Math.cos(TAU*pitch),
           Math.sin(TAU*yaw)*Math.cos(TAU*pitch), Math.sin(TAU*pitch)],
  };
}

export function primaryUvPrecomputed(point, position, pre, textureScale, stretch=1, flip=0) {
  const q = pre.axis, [ct, st, cb, sb] = pre.trig;
  const dp = q[0]*point[0]+q[1]*point[1]+q[2]*point[2];
  const qq = q[0]*q[0]+q[1]*q[1]+q[2]*q[2];
  const r = q.map((x, i) => 2*x*dp-qq*point[i]);
  const x = ct*r[0]-st*r[1]-position[0], y = st*r[0]+ct*r[1]+position[1];
  const u = cb*x-sb*y, v = sb*x+cb*y, s = 255*textureScale;
  return [(u-0.5)/(s*stretch)+0.5, (v-0.5)/(s*(1-2*flip))+0.5];
}

export function mirrorUvPrecomputed(point, position, pre, textureScale, stretch=1, flip=0) {
  const mirror = { axis: [pre.axis[0], -pre.axis[1], pre.axis[2]],
    trig: [-pre.trig[0], pre.trig[1], pre.trig[2], -pre.trig[3]] };
  return primaryUvPrecomputed(point, [position[0]+1, position[1]], mirror,
    textureScale, -stretch, flip);
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
// Hot-path form: axis and all angular trig are uniforms computed once on the CPU.
// trig = cos/sin of TAU*(-yaw-0.25), followed by cos/sin of TAU*roll.
vec2 mtDecalPrimaryUvPre(vec3 p, vec2 PositionXPositionY, vec3 q, vec4 trig,
                         float TextureScale, float Stretch, float Flip) {
  vec3 r = 2.0*q*dot(q, p) - dot(q, q)*p;
  float x = trig.x*r.x - trig.y*r.y - PositionXPositionY.x;
  float y = trig.y*r.x + trig.x*r.y + PositionXPositionY.y;
  vec2 v = vec2(trig.z*x - trig.w*y, trig.w*x + trig.z*y);
  vec2 d = vec2(255.0*TextureScale*Stretch,
                255.0*TextureScale*(1.0-2.0*Flip));
  return (v - 0.5)/d + 0.5;
}
vec2 mtDecalMirrorUvPre(vec3 p, vec2 PositionXPositionY, vec3 q, vec4 trig,
                        float TextureScale, float Stretch, float Flip) {
  return mtDecalPrimaryUvPre(p, PositionXPositionY + vec2(1.0, 0.0),
    vec3(q.x, -q.y, q.z), vec4(-trig.x, trig.y, trig.z, -trig.w),
    TextureScale, -Stretch, Flip);
}
float mtDecalEdge(float u) {
  return clamp((1.0 - 2.0*abs(u - 0.5))*100000.0, 0.0, 1.0);
}
`;
