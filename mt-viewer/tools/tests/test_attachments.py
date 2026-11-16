import math
import unittest

from tools.attachments import attachment_to_part, component_to_part


class AttachmentTransformTests(unittest.TestCase):
    def test_vamos_attachment_transform(self):
        record = {
            'slot': '149',
            'strings': ['Attachment_LED_Strip_02', ''],
            'ints': [1],
            'vectors': [
                {'X': -377.00009155273, 'Y': 133, 'Z': 423},
                {'X': 0, 'Y': 0, 'Z': 90},
                {'X': 1, 'Y': 1, 'Z': 1},
            ],
        }
        part = attachment_to_part(record)
        self.assertEqual(part['key'], 'Attachment_LED_Strip_02')
        self.assertEqual(part['slot'], '149')
        for got, want in zip(part['position'], [-3.7700009155273, 4.23, -1.33]):
            self.assertAlmostEqual(got, want)
        self.assertEqual(part['scale'], [1, 1, 1])
        expected = [0.0, math.sqrt(0.5), 0.0, math.sqrt(0.5)]
        for got, want in zip(part['rotation'], expected):
            self.assertAlmostEqual(got, want)

    def test_optional_scale_uses_gltf_axis_order(self):
        record = {'slot': '1', 'strings': ['Attachment_X'], 'vectors': [
            {'X': 0, 'Y': 0, 'Z': 0}, {'X': 0, 'Y': 0, 'Z': 0},
            {'X': 2, 'Y': 3, 'Z': 4},
        ]}
        self.assertEqual(attachment_to_part(record)['scale'], [2, 4, 3])

    def test_actor_component_named_rotator(self):
        component = {
            'Name': 'LED1_GEN_VARIABLE',
            'Properties': {
                'RelativeLocation': {'X': 0, 'Y': 25, 'Z': 0},
                'RelativeRotation': {'Pitch': -90, 'Yaw': 0, 'Roll': 0},
            },
        }
        part = component_to_part(component)
        self.assertEqual(part['position'], [0.0, 0.0, -0.25])
        self.assertEqual(part['scale'], [1, 1, 1])
        expected = [0.0, 0.0, -math.sqrt(0.5), math.sqrt(0.5)]
        for got, want in zip(part['rotation'], expected):
            self.assertAlmostEqual(got, want)


if __name__ == '__main__':
    unittest.main()
