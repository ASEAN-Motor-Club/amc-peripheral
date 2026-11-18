// Motor Town attachment actors use the opposite local forward convention from
// the vehicle attachment transform for most meshes. Light actors are the
// exception: their component transforms and light rotations are authored in the
// vehicle basis, so applying the 180-degree mesh correction points every lamp
// (and its emission cone) at the opposite end of the car.
export function attachmentRootRotation(source = [0, 0, 0, 1], actorBasis = null) {
  if (actorBasis && actorBasis[0] === 0 && actorBasis[1] === 0 &&
      actorBasis[2] === 0 && actorBasis[3] === 1) {
    return [...source];
  }
  const [x, y, z, w] = source;
  return [-z, w, x, -y]; // yaw180 * source for mesh-basis actors
}
