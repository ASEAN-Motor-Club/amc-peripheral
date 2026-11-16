import assert from 'node:assert/strict';
import { primaryUv, mirrorUv, decalPrecompute, primaryUvPrecomputed, mirrorUvPrecomputed, DECAL_PROJECTION_GLSL } from '../../site/js/decal-projection.js';

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
  const [point, position, yaw, pitch, roll, scale, stretch, flip] = c.args;
  const pre = decalPrecompute([yaw,pitch,roll].map(v => v*360));
  const pp = primaryUvPrecomputed(point, position, pre, scale, stretch, flip);
  const pm = mirrorUvPrecomputed(point, position, pre, scale, stretch, flip);
  for (let i=0;i<2;i++) {
    assert.ok(Math.abs(pp[i]-p[i]) < 1e-12, `precomputed primary mismatch ${pp[i]} != ${p[i]}`);
    assert.ok(Math.abs(pm[i]-m[i]) < 1e-12, `precomputed mirror mismatch ${pm[i]} != ${m[i]}`);
    assert.ok(Math.abs(p[i]-c.primary[i]) < 1e-12, `${p[i]} != ${c.primary[i]}`);
    assert.ok(Math.abs(m[i]-c.mirror[i]) < 1e-12, `${m[i]} != ${c.mirror[i]}`);
  }
}
let seed = 0x4d544465;
const random = () => ((seed = (1664525*seed + 1013904223) >>> 0) / 0x100000000);
for (let n=0; n<1000; n++) {
  const point = [-500,250,50].map((v,i) => v+(random()-0.5)*400);
  const position = [(random()-0.5)*300,(random()-0.5)*600];
  const turns = [(random()-0.5)*4,(random()-0.5)*4,(random()-0.5)*4];
  const scale = 0.05+random()*8, stretch = 0.1+random()*2, flip = n%2;
  const args = [point,position,...turns,scale,stretch,flip];
  const pre = decalPrecompute(turns.map(v => v*360));
  const p = primaryUv(...args), pp = primaryUvPrecomputed(point,position,pre,scale,stretch,flip);
  const m = mirrorUv(...args), pm = mirrorUvPrecomputed(point,position,pre,scale,stretch,flip);
  for (let i=0;i<2;i++) {
    assert.ok(Math.abs(pp[i]-p[i])<1e-12, `sweep primary ${n}/${i}`);
    assert.ok(Math.abs(pm[i]-m[i])<1e-12, `sweep mirror ${n}/${i}`);
  }
}
for (const token of ['255.0', 'PositionX', 'mtDecalPrimaryUv', 'mtDecalMirrorUv'])
  assert.ok(DECAL_PROJECTION_GLSL.includes(token), `missing GLSL token ${token}`);
console.log('decal projection JS: 3 reference cases + 1000 primary/mirror sweep cases passed');
