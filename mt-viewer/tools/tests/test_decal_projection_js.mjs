import assert from 'node:assert/strict';
import { primaryUv, mirrorUv, primaryVisibility, mirrorVisibility, DECAL_PROJECTION_GLSL } from '../../site/js/decal-projection.js';

const cases = [
  {
    args: [[100,200,300],[0,0],0,0,0,1,1,0],
    primary: [-0.28627450980392144,-0.6784313725490199],
    mirror: [1.2901960784313724,-0.6784313725490199],
  },
  {
    args: [[120,-240,360],[20,30],0.17,-0.11,0.08,1.3,1.7,0],
    primary: [0.9396956240877928,0.39328962632865083],
    mirror: [0.8748506977182602,-0.5919385816330369],
  },
  {
    args: [[-500,250,50],[-80,190],0.73,0.22,-0.31,4.3740282058716,0.71635884046555,1],
    primary: [0.2178489557555695,1.00629021844455],
    mirror: [0.888245643255672,0.9823305581897432],
  },
];
for (const c of cases) {
  const p = primaryUv(...c.args), m = mirrorUv(...c.args);
  for (let i=0;i<2;i++) {
    assert.ok(Math.abs(p[i]-c.primary[i]) < 1e-12, `${p[i]} != ${c.primary[i]}`);
    assert.ok(Math.abs(m[i]-c.mirror[i]) < 1e-12, `${m[i]} != ${c.mirror[i]}`);
  }
}
const CULL_BOTH = 4 | 8;
// DXBC 5020: primary opposite-cull reads LocalBounds (r4), backface-cull reads
// LocalNormal (r3). The mirror block repeats that same pairing with cb2[15].
assert.equal(primaryVisibility([100,0,0], [1,0,0], 0, 0, CULL_BOTH), 1);
assert.equal(primaryVisibility([-100,0,0], [1,0,0], 0, 0, CULL_BOTH), 0);
assert.equal(primaryVisibility([100,0,0], [-1,0,0], 0, 0, CULL_BOTH), 0);
assert.equal(primaryVisibility([0,100,0], [0,1,0], 0.25, 0, CULL_BOTH), 1);
assert.equal(mirrorVisibility([0,100,0], [0,1,0], 0.25, 0, CULL_BOTH), 0);
assert.equal(mirrorVisibility([0,-100,0], [0,-1,0], 0.25, 0, CULL_BOTH), 1);

for (const token of ['255.0', 'PositionX', 'mtDecalPrimaryUv', 'mtDecalMirrorUv', 'mtDecalVisibility'])
  assert.ok(DECAL_PROJECTION_GLSL.includes(token), `missing GLSL token ${token}`);
console.log('decal projection JS: 3 primary + 3 mirror reference cases passed');
