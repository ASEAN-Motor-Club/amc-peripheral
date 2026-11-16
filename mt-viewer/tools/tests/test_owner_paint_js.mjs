import assert from 'node:assert/strict';
import { ownerColorForSlot } from '../../site/js/owner-paint.js';

const orange = [187, 130, 0, 255];
const dark = [41, 42, 48, 255];
const colors = { Body_01: orange, CargoBed_01: dark, Cargobed_02: dark };
const colourKeys = ['Body_01', 'CargoBed_01', 'CargoBed_02'];
const extra = { Palette: 0 };

assert.equal(ownerColorForSlot('Body_01', colors, colourKeys, extra), orange);
assert.equal(ownerColorForSlot('Palette', colors, colourKeys, extra), orange,
  'main Palette shell inherits the first body colour');
assert.equal(ownerColorForSlot('CargoBed_02', colors, colourKeys, extra), dark,
  'workshop slot-name casing is not significant');
assert.equal(ownerColorForSlot('Body_02', { Body: orange }, colourKeys, extra), orange,
  'numeric slot suffix falls back to the base slot');
assert.equal(ownerColorForSlot('Seat_01', colors, colourKeys, extra), undefined,
  'unpainted slots stay at their material default');
console.log('owner paint: Palette inheritance and slot-alias cases passed');
