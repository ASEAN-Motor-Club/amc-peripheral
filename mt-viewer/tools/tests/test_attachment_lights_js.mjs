import assert from 'node:assert/strict';
import { spotlightTarget } from '../../site/js/attachment-lights.js';

const close = (actual, expected) => actual.forEach((v, i) => assert.ok(Math.abs(v - expected[i]) < 1e-9, `${v} != ${expected[i]}`));
const mul = (a, b) => {
  const [ax, ay, az, aw] = a, [bx, by, bz, bw] = b;
  return [aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx,
    aw*bz + ax*by - ay*bx + az*bw, aw*bw - ax*bx - ay*by - az*bz];
};
const r = Math.SQRT1_2;
const align = [0, r, 0, r];
close(spotlightTarget([2, 3, 4], align), [1, 3, 4]); // identity UE light: +X mapped to -X
const up = mul([0, 0, r, r], align); // UE pitch +90: +Z -> viewer +Y
close(spotlightTarget([2, 3, 4], up), [2, 2, 4]);
const rear = mul([0, 1, 0, 0], align); // UE yaw 180: +X
close(spotlightTarget([2, 3, 4], rear), [3, 3, 4]);
console.log('attachment spotlight targets: forward, pitched and rearward cases passed');
