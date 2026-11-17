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

    def test_native_dashboard_uses_centered_steering_reference(self):
        manifest = {'parts': [{
            'id': 'Dashboard', 'class': 'MTDashboard', 'mesh': 'Dashboard_01',
            'position': [0.14, 0.01, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1],
        }]}
        sockets = [{'name': 'SteeringWheel', 'loc': [66.046104, -46.357258, 88.212555],
                    'rot': [0, 0, 0], 'scale': [1, 1, 1]}]
        result = self.run_manifest(manifest, sockets)
        part = result['parts'][0]
        self.assertEqual(part['position'], [0.80046, 0.89213, 0.0])
        self.assertEqual(part['mountedOn'], 'socket:SteeringWheel')
        self.assertEqual(part['socketLateralCentered'], True)
        self.assertEqual(part['socketLocal']['position'], [0.14, 0.01, 0])
        self.assertEqual(self.run_manifest(result, sockets), result)

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

    def test_scs_socket_composes_with_component_local_offset_idempotently(self):
        manifest = {'parts': [{
            'id': 'MTVehicleDoor_GEN_VARIABLE', 'attachSocket': 'Hook_6x4',
            'position': [0, -0.04, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1],
        }]}
        sockets = [{'name': 'Hook_6x4', 'loc': [-60.913258, 0, 120.00001],
                    'rot': [0, 0, 0], 'scale': [1, 1, 1]}]
        result = self.run_manifest(manifest, sockets)
        part = result['parts'][0]
        self.assertEqual(part['position'], [-0.60913, 1.16, -0.0])
        self.assertEqual(part['mountedOn'], 'socket:Hook_6x4')
        self.assertEqual(part['socketLocal']['position'], [0, -0.04, 0])
        self.assertEqual(self.run_manifest(result, sockets), result)

    def test_stock_part_slot_uses_rear_wing_socket(self):
        manifest = {'parts': [{
            'id': 'Vista_RearWing_01', 'partSlot': 'RearWing',
            'position': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1],
        }]}
        sockets = [{'name': 'RearWing', 'loc': [-228.86314, 0, 104.161644],
                    'rot': [0, 0, 0], 'scale': [1, 1, 1]}]
        part = self.run_manifest(manifest, sockets)['parts'][0]
        self.assertEqual(part['position'], [-2.28863, 1.04162, -0.0])
        self.assertEqual(part['mountedOn'], 'socket:RearWing')


    def test_native_steering_preserves_small_socket_local_offset(self):
        part = {
            'id': 'SteeringWheel', 'mesh': 'Large_1Spoke_01',
            'position': [-0.02, 0, 0], 'rotation': [0, 0, 0, 1],
            'scale': [1, 1, 1],
        }
        result = self.run_manifest({'parts': [part]}, [{
            'name': 'SteeringWheel', 'loc': [500, 0, 0], 'rot': [0, 0, 0], 'scale': [1, 1, 1],
        }])['parts'][0]
        self.assertAlmostEqual(result['position'][0], 4.98)
        self.assertEqual(result['socketLocal']['position'], [-0.02, 0, 0])
        self.assertEqual(result['mountedOn'], 'socket:SteeringWheel')

    def test_vehicle_space_steering_is_not_snapped_twice(self):
        part = {
            'id': 'SteeringWheel', 'mesh': 'SteeringWheel',
            'position': [1.5, 0.9, 0], 'rotation': [0, 0, 0, 1],
            'scale': [1, 1, 1],
        }
        result = self.run_manifest({'parts': [part]})['parts'][0]
        self.assertEqual(result['position'], [1.5, 0.9, 0])
        self.assertNotIn('mountedOn', result)

    def test_zero_handlebar_stays_in_authored_vehicle_space(self):
        part = {
            'id': 'SteeringWheel', 'mesh': 'Handlebar',
            'position': [0.42971, 0.96908, -0.00005],
            'rotation': [0, 0, -0.53018, 0.847885], 'scale': [1, 1, 1],
            'mountedOn': 'socket:SteeringWheel',
            'socketLocal': {'position': [0, 0, 0]},
        }
        result = self.run_manifest({'parts': [part]})['parts'][0]
        self.assertEqual(result['position'], [0, 0, 0])
        self.assertEqual(result['rotation'], [0, 0, 0, 1])
        self.assertNotIn('mountedOn', result)
        self.assertNotIn('socketLocal', result)


class ConstructionScriptSocketTests(unittest.TestCase):
    def test_attach_to_name_is_mapped_to_component_template(self):
        exports = [{'Class': 'SCS_Node', 'Properties': {
            'ComponentTemplate': {'ObjectName': 'MTVehicleDoor_GEN_VARIABLE'},
            'AttachToName': 'Hook_6x4',
        }}]
        from tools.mk_manifest import component_socket_names
        self.assertEqual(component_socket_names(exports), {
            'MTVehicleDoor_GEN_VARIABLE': 'Hook_6x4',
        })

    def test_native_dashboard_defaults_to_steering_socket_with_mesh_local_transform(self):
        from tools.mk_manifest import dashboard_local, dashboard_socket
        props = {
            'DashboardMeshLocation': {'DashboardMeshLocation': {'X': 5, 'Y': 0, 'Z': 2}},
            'DashboardMeshRotation': {'DashboardMeshRotation': {
                'Pitch': -5, 'Yaw': 0, 'Roll': 0,
            }},
        }
        self.assertEqual(dashboard_socket(props), 'SteeringWheel')
        loc, q, scale = dashboard_local(props)
        self.assertEqual(loc, (5, 0, 2))
        self.assertNotEqual(q, (0, 0, 0, 1))
        self.assertEqual(scale, (1, 1, 1))

    def test_mesh_dashboard_uses_vehicle_space_without_socket(self):
        from tools.mk_manifest import dashboard_socket
        self.assertIsNone(dashboard_socket({'DashboardMeshComponentName': 'Mesh'}))
        self.assertEqual(dashboard_socket({
            'DashboardMeshComponentName': 'SteeringWheel',
        }), 'SteeringWheel')

    def test_alternate_socket_packages_use_distinct_sidecars(self):
        from tools.fetch_sockets import sidecar_path
        first = sidecar_path('/tmp/build', 'Frame', '/Game/Cars/Models/Atlas/Frame', 0)
        second = sidecar_path('/tmp/build', 'Frame', '/Game/Cars/Models/Atlas/Cab', 1)
        self.assertNotEqual(first, second)
        self.assertTrue(first.endswith('Frame__0_Frame.sockets.json'))
        self.assertTrue(second.endswith('Frame__1_Cab.sockets.json'))

    def test_fetch_targets_include_scs_and_known_stock_slots_only(self):
        from tools.fetch_sockets import required_sockets
        manifest = {'parts': [
            {'id': 'Door', 'attachSocket': 'Hook_6x4'},
            {'id': 'Wing', 'partSlot': 'RearWing'},
            {'id': 'Bumper', 'partSlot': 'FrontBumper'},
            {'id': 'SteeringWheel'},
        ]}
        self.assertEqual(required_sockets(manifest), {
            'Hook_6x4', 'RearWing', 'SteeringWheel',
        })
        self.assertEqual(required_sockets(manifest, attachments_only=True), {
            'Hook_6x4', 'RearWing',
        })


if __name__ == '__main__':
    unittest.main()
