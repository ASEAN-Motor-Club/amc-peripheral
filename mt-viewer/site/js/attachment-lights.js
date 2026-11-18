export function spotlightTarget(position, quaternion) {
  const [x, y, z, w] = quaternion;
  // Apply the final light quaternion to Three.js's local forward vector (0,0,-1).
  const vx = 0, vy = 0, vz = -1;
  const ix = w * vx + y * vz - z * vy;
  const iy = w * vy + z * vx - x * vz;
  const iz = w * vz + x * vy - y * vx;
  const iw = -x * vx - y * vy - z * vz;
  const direction = [
    ix * w + iw * -x + iy * -z - iz * -y,
    iy * w + iw * -y + iz * -x - ix * -z,
    iz * w + iw * -z + ix * -y - iy * -x,
  ];
  return position.map((value, index) => value + direction[index]);
}
