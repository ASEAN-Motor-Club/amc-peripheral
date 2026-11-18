import assert from 'node:assert/strict';
import { primaryUv, mirrorUv, primaryVisibility, mirrorVisibility, decalFallbackSlots, decalReceiverSlots, DECAL_PROJECTION_GLSL } from '../../site/js/decal-projection.js';
import { liverySlotMatches } from '../../site/js/body-material.js';

const cases = [
  {
    args: [[100,200,300],[0,0],0,0,0,1,1,0],
    primary: [-0.28627450980392144,-0.6784313725490199],
    mirror: [1.2823529411764705,-0.6784313725490199],
  },
  {
    args: [[120,-240,360],[20,30],0.17,-0.11,0.08,1.3,1.7,0],
    primary: [0.8418650049513459,-0.6211080612510504],
    mirror: [0.2533071506639494,-0.24985569475546476],
  },
  {
    args: [[-500,250,50],[-80,190],0.73,0.22,-0.31,4.3740282058716,0.71635884046555,1],
    primary: [1.2419592964274586,0.34008637620862286],
    mirror: [0.7055260476018118,0.1261927497052795],
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

const slotDefs = {
  Body_01: { materialName: 'MotorTown/Content/Cars/Materials/Body/M_Body/M_Body' },
  Seat_01: { materialName: 'MotorTown/Content/Cars/Materials/M_Seat' },
  Seat_02: { materialName: 'MotorTown/Content/Cars/Materials/M_Seat' },
  Palette: { materialName: 'MotorTown/Content/Cars/Materials/M_Palette' },
  Mat_PolygonCity_Texture_01_A_001: { materialName: 'MotorTown/Content/Cars/Materials/MI_PolygonCity_01_A' },
};
const bodyVariants = [
  { index: 0, material: 'MotorTown/Content/Cars/Materials/Body/M_Body/M_Body' },
  { index: 1, material: 'MotorTown/Content/Cars/Materials/M_Palette' },
];
assert.deepEqual([...decalFallbackSlots([], slotDefs, bodyVariants, 0)].sort(),
  ['Body_01', 'Palette']);
assert.deepEqual([...decalFallbackSlots([], slotDefs, bodyVariants, -1)].sort(),
  ['Body_01', 'Palette']);
assert.equal(decalFallbackSlots([], slotDefs, bodyVariants, 4).size, 2);
assert.deepEqual([...decalFallbackSlots([], slotDefs, bodyVariants, 4)].sort(),
  ['Body_01', 'Palette']);
assert.deepEqual([...decalFallbackSlots([], slotDefs, [], -1)].sort(),
  ['Body_01', 'Palette']);
assert.equal(decalFallbackSlots(['CargoBed_01'], slotDefs, bodyVariants, 0).size, 0);

// Nuke's exported shell slot is named Seats_01 but runs the generic body shader.
const nukeDefs = {
  Body_01: { materialName: 'M_Body' },
  Seats_01: { materialName: 'M_Body' },
  Palette: { materialName: 'M_Palette' },
};
assert.deepEqual([...decalReceiverSlots(['Body_01'], nukeDefs, { Body_01: 2, Seats_01: 6.5 })].sort(),
  ['Body_01', 'Seats_01']);
assert.deepEqual([...decalReceiverSlots([], nukeDefs, { Body_01: 6.5, Seats_01: 2 })].sort(),
  ['Body_01']);
assert.deepEqual([...decalReceiverSlots(['Body'], {
  Body: { materialName: 'M_Body' },
  Body_0: { materialName: 'M_Body' },
  Seat: { materialName: 'M_Body' },
}, { Body: 2.24, Body_0: 2.25, Seat: 0.65 })].sort(),
  ['Body', 'Body_0']);
assert.deepEqual([...decalReceiverSlots(['Body_01'], nukeDefs)], ['Body_01']);
assert.deepEqual([...decalReceiverSlots(['Body_01'], { Body_01: { materialName: 'Mat_PolygonStreetRacer_Car_Instance_16' } })],
  ['Body_01']);

assert.equal(liverySlotMatches({ materialName: 'M_Body' }, { materialName: 'M_Body' }), true);
assert.equal(liverySlotMatches({ materialName: 'M_Palette' }, { materialName: 'M_Body' }), false);
assert.equal(liverySlotMatches({ materialName: 'M_Palette' }, { materialName: 'M_Palette' }), true);
assert.equal(liverySlotMatches({}, null), true);

for (const token of ['255.0', 'PositionX', 'mtDecalPrimaryUv', 'mtDecalMirrorUv', 'mtDecalVisibility'])
  assert.ok(DECAL_PROJECTION_GLSL.includes(token), `missing GLSL token ${token}`);
console.log('decal projection JS: 3 primary + 3 mirror reference cases passed');
