import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { meshopt } from '@gltf-transform/functions';
import { MeshoptDecoder, MeshoptEncoder } from 'meshoptimizer';
import fs from 'node:fs/promises';
import path from 'node:path';

const files = process.argv.slice(2);
if (!files.length) throw new Error('usage: node compress_glb.mjs FILE...');
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  'meshopt.decoder': MeshoptDecoder,
  'meshopt.encoder': MeshoptEncoder,
});
for (const file of files) {
  const before = (await fs.stat(file)).size;
  const document = await io.read(file);
  await document.transform(meshopt({ encoder: MeshoptEncoder, level: 'high' }));
  const temporary = `${file}.${process.pid}.tmp.glb`;
  await io.write(temporary, document);
  const after = (await fs.stat(temporary)).size;
  await fs.rename(temporary, file);
  console.log(JSON.stringify({ file: path.basename(file), before, after, saving: 1 - after / before }));
}
