import { Document, NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { mergeDocuments, join, meshopt, prune, simplify, unpartition, weld } from '@gltf-transform/functions';
import { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } from 'meshoptimizer';
import fs from 'node:fs/promises';
import path from 'node:path';

const [siteRoot, slug, ratioArg = '0.12'] = process.argv.slice(2);
if (!siteRoot || !slug) throw new Error('usage: node build_preview.mjs SITE_ROOT SLUG [RATIO]');
const vehicleRoot = path.join(siteRoot, slug);
const manifestPath = path.join(vehicleRoot, `${slug}.json`);
const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
const parts = manifest.parts.filter(p => !p.hidden && !p.attachToWheel && p.glb);
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  'meshopt.decoder': MeshoptDecoder,
  'meshopt.encoder': MeshoptEncoder,
});
const target = new Document();
const buffer = target.createBuffer();
const scene = target.createScene('preview');
target.getRoot().setDefaultScene(scene);
const material = target.createMaterial('Preview').setBaseColorFactor([0.62, 0.71, 0.82, 1]);

for (const part of parts) {
  let source;
  try {
    source = await io.read(path.join(vehicleRoot, 'glb', part.glb));
  } catch (error) {
    if (part.mesh === 'Body') throw error;
    console.warn(`preview: skipping unavailable ${slug}/${part.glb}`);
    continue;
  }
  const before = new Set(target.getRoot().listScenes());
  mergeDocuments(target, source);
  const wrapper = target.createNode(part.id).setTranslation(part.position)
    .setRotation(part.rotation).setScale(part.scale);
  scene.addChild(wrapper);
  for (const mergedScene of target.getRoot().listScenes().filter(s => !before.has(s) && s !== scene)) {
    for (const child of mergedScene.listChildren()) wrapper.addChild(child);
    mergedScene.dispose();
  }
}

for (const mesh of target.getRoot().listMeshes()) {
  for (const primitive of mesh.listPrimitives()) primitive.setMaterial(material);
}
await target.transform(
  weld(),
  simplify({ simplifier: MeshoptSimplifier, ratio: Number(ratioArg), error: 0.01 }),
);
for (const mesh of target.getRoot().listMeshes()) {
  for (const primitive of mesh.listPrimitives()) {
    for (const semantic of primitive.listSemantics()) {
      if (semantic !== 'POSITION') primitive.setAttribute(semantic, null);
    }
  }
}
await target.transform(
  join({ keepNamed: false }),
  prune({ keepAttributes: false, keepLeaves: false }),
);
await target.transform(unpartition());
await target.transform(meshopt({ encoder: MeshoptEncoder, level: 'high' }));
const output = path.join(vehicleRoot, 'preview.glb');
await io.write(output, target);
const stat = await fs.stat(output);
manifest.preview = { glb: 'preview.glb', bytes: stat.size, ratio: Number(ratioArg), parts: parts.length };
await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 1) + '\n');
console.log(JSON.stringify({ slug, sourceParts: parts.length, bytes: stat.size, output }));
