import assert from 'node:assert/strict';
import { selectedBodyVariant } from '../../site/js/body-material.js';

const variants = [{ index: 2, materialName: 'M_Decal' }, { index: 7, materialName: 'M_Body' }];
assert.equal(selectedBodyVariant(variants, 7)?.materialName, 'M_Body');
assert.equal(selectedBodyVariant(variants, 0), null, 'numeric index is not an array position');
assert.equal(selectedBodyVariant([{ materialName: 'M_Body' }], 0)?.materialName, 'M_Body',
  'legacy baked arrays retain positional compatibility');
assert.equal(selectedBodyVariant(variants, -1), null);
assert.equal(selectedBodyVariant(variants, NaN), null);
console.log('body material: numeric workshop selection passed');
