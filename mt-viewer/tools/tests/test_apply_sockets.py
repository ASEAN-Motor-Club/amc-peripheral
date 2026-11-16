import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import apply_sockets


class SteeringWheelSocketTests(unittest.TestCase):
    def run_manifest(self, manifest, sockets=()):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            glb = root / 'glb'
            glb.mkdir()
            if sockets:
                (glb / 'Body.sockets.json').write_text(json.dumps(sockets))
            path = root / 'vehicle.json'
            path.write_text(json.dumps(manifest))
            with patch.object(apply_sockets.sys, 'argv', ['apply_sockets.py', str(path), str(glb)]):
                apply_sockets.main()
            return json.loads(path.read_text())

    def test_origin_steering_wheel_without_socket_is_omitted(self):
        manifest = {'parts': [
            {'id': 'Body', 'mesh': 'Body', 'position': [0, 0, 0]},
            {'id': 'SteeringWheel', 'mesh': 'Large_1Spoke_01', 'position': [0, 0, -0.0]},
        ]}
        result = self.run_manifest(manifest)
        self.assertEqual([p['id'] for p in result['parts']], ['Body', 'SteeringWheel'])
        self.assertEqual(result['parts'][1]['hidden'], True)

    def test_non_steering_origin_part_is_preserved(self):
        part = {'id': 'ControlPanel', 'position': [0, 0, 0]}
        result = self.run_manifest({'parts': [part]})
        self.assertEqual(result['parts'], [part])

    def test_already_mounted_part_is_not_dropped_when_sidecar_is_missing(self):
        part = {'id': 'SteeringWheel', 'position': [0, 0, 0],
                'mountedOn': 'socket:SteeringWheel'}
        result = self.run_manifest({'parts': [part]})
        self.assertIn(part, result['parts'])

    def test_explicit_steering_wheel_transform_is_preserved(self):
        part = {'id': 'SteeringWheel', 'mesh': 'Boxy', 'position': [1, 2, 3]}
        result = self.run_manifest({'parts': [part]})
        self.assertEqual(result['parts'], [part])

    def test_origin_steering_wheel_uses_socket_when_present(self):
        manifest = {'parts': [{'id': 'SteeringWheel', 'position': [0, 0, 0], 'hidden': True}]}
        sockets = [{'name': 'SteeringWheel', 'loc': [100, 200, 300],
                    'rot': [0, 0, 0], 'scale': [1, 1, 1]}]
        result = self.run_manifest(manifest, sockets)
        part = result['parts'][0]
        self.assertEqual(part['position'], [1.0, 3.0, -2.0])
        self.assertEqual(part['mountedOn'], 'socket:SteeringWheel')
        self.assertNotIn('hidden', part)


if __name__ == '__main__':
    unittest.main()
