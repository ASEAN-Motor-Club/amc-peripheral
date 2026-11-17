import unittest

from tools.mk_manifest import apply_native_hub_mounts


class NativeHubMountTests(unittest.TestCase):
    def test_front_rod_hub_uses_front_axle_and_metre_geometry(self):
        parts = [
            {
                'id': 'Wheel0', 'position': [0.77729, 0.343, 0],
                'rotation': [0, 0, 0, 1], 'scale': [0.68193] * 3,
            },
            {
                'id': 'FrontArmStaticMesh_GEN_VARIABLE', 'attachSocket': 'FrontRodHub',
                'position': [0, 0, 0], 'rotation': [0, -0.707107, 0, 0.707107],
                'scale': [0.01, 0.01, 0.01],
            },
        ]
        apply_native_hub_mounts(parts)
        fork = parts[1]
        self.assertEqual(fork['position'], [0.77729, 0.343, 0])
        self.assertEqual(fork['scale'], [1, 1, 1])
        self.assertEqual(fork['sourceUnitCompensation'], [0.01, 0.01, 0.01])
        self.assertEqual(fork['mountedOn'], 'native-hub:Wheel0')
        # Wheel visual scale must not leak into the native hub/fork transform.
        self.assertEqual(fork['rotation'], [0, -0.707107, 0, 0.707107])
        before = [dict(fork)]
        apply_native_hub_mounts(parts)
        self.assertEqual(parts[1], before[0])

    def test_unrelated_socket_mount_is_unchanged(self):
        parts = [{'id': 'Wheel0', 'position': [1, 2, 3]},
                 {'id': 'Body', 'attachSocket': 'SteeringWheel', 'position': [0, 0, 0]}]
        apply_native_hub_mounts(parts)
        self.assertEqual(parts[1]['position'], [0, 0, 0])


if __name__ == '__main__':
    unittest.main()
