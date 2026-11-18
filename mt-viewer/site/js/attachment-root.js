// Motor Town attachment actors use the opposite local forward convention from
// the vehicle attachment transform. Apply one shared correction to the complete
// actor: meshes, component offsets, and emission directions all inherit it.
export function attachmentRootRotation(source = [0, 0, 0, 1]) {
  const [x, y, z, w] = source;
  return [-z, w, x, -y]; // yaw180 * source
}
