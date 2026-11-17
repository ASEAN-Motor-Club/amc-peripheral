import assert from 'node:assert/strict';
import { attachmentRootRotation } from '../../site/js/attachment-root.js';

const close = (actual, expected) => actual.forEach((v, i) => assert.ok(Math.abs(Math.abs(v) - Math.abs(expected[i])) < 1e-9));
close(attachmentRootRotation([0, 0, 0, 1]), [0, 1, 0, 0]);
close(attachmentRootRotation([0, Math.SQRT1_2, 0, Math.SQRT1_2]), [0, Math.SQRT1_2, 0, Math.SQRT1_2]);
close(attachmentRootRotation([0, 0, Math.SQRT1_2, Math.SQRT1_2]), [-Math.SQRT1_2, Math.SQRT1_2, 0, 0]);
assert.deepEqual(attachmentRootRotation([0.1, 0.2, 0.3, 0.9], [0, 0, 0, 1]), [0.1, 0.2, 0.3, 0.9]);
close(attachmentRootRotation([0, 0, 0, 1], [0, 1, 0, 0]), [0, 1, 0, 0]);
console.log('attachment root: default correction and authored-basis override passed');
