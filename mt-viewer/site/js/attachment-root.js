// Motor Town attachment actors use the opposite local forward convention from
// the vehicle attachment transform. Apply one shared correction to the complete
// actor: meshes, component offsets, and emission directions all inherit it.
export function attachmentRootRotation(source = [0, 0, 0, 1], actorBasis = null) {
  if (actorBasis && actorBasis[0] === 0 && actorBasis[1] === 0 &&
      actorBasis[2] === 0 && actorBasis[3] === 1) {
    return [...source]; // authored bidirectional actor basis
  }
  const [x, y, z, w] = source;
  return [-z, w, x, -y]; // default mesh-basis correction
}
