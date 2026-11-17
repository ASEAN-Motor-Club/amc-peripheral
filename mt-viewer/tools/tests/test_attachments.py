import json
import math
import unittest
from pathlib import Path

from tools.attachments import attachment_to_part, component_to_part, rect_light_to_part, spot_light_to_part


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
    def test_blue_rect_light(self):
        component = {
            'Type': 'RectLightComponent', 'IntensityNits': 19.199999,
            'Properties': {
                'SourceWidth': 50, 'SourceHeight': 5, 'AttenuationRadius': 150,
                'BarnDoorAngle': 90, 'LightColor': {'R': 0, 'G': 0, 'B': 255},
                'RelativeLocation': {'X': 0, 'Y': 0, 'Z': -0.5},
                'RelativeRotation': {'Pitch': -90, 'Yaw': 0, 'Roll': 0},
                'CastShadows': False,
            },
        }
        light = rect_light_to_part(component)
        self.assertEqual(light['type'], 'rect')
        self.assertEqual(light['position'], [0.0, -0.005, 0.0])
        self.assertEqual(light['width'], 0.5)
        self.assertEqual(light['height'], 0.05)
        self.assertEqual(light['intensity'], 19.199999)
        self.assertEqual(light['color'], [0.0, 0.0, 1.0])
        self.assertEqual(light['attenuationRadius'], 1.5)
        self.assertEqual(light['barnDoorAngle'], 90)
        self.assertFalse(light['castShadows'])
    def test_rect_light_requires_cooked_nits_and_area(self):
        with self.assertRaises(ValueError):
            rect_light_to_part({'Type': 'RectLightComponent', 'Properties': {'Intensity': 10}})


class SpotLightTests(unittest.TestCase):
    def test_lumens_are_converted_to_candela_for_source_cone(self):
        light = spot_light_to_part({
            'Type': 'SpotLightComponent',
            'Properties': {
                'Intensity': 50,
                'IntensityUnits': 'ELightUnits::Lumens',
                'OuterConeAngle': 50,
                'InnerConeAngle': 20,
                'AttenuationRadius': 500,
                'LightColor': {'R': 255, 'G': 166, 'B': 0},
            },
        })
        expected = 50 / (2 * math.pi * (1 - math.cos(math.radians(50))))
        self.assertAlmostEqual(light['intensity'], expected)
        self.assertEqual(light['sourceIntensity'], 50)
        self.assertEqual(light['outerConeAngle'], 50)
        self.assertEqual(light['innerConeAngle'], 20)
        self.assertEqual(light['attenuationRadius'], 5)
        self.assertEqual(light['color'], [1.0, 166 / 255, 0.0])


class AttachmentCatalogTests(unittest.TestCase):
    def test_two_metre_blue_and_red_variants_are_catalogued(self):
        catalog_path = Path(__file__).parents[2] / 'site' / 'attachments' / 'catalog.json'
        actors = json.loads(catalog_path.read_text())['actors']
        green = actors['Attachment_LED_Strip_02']
        for key, color, source in [
            ('Attachment_LED_Strip_01', [0.0, 0.0, 1.0], 'led_blue_2m'),
            ('Attachment_LED_Strip_03', [1.0, 0.0, 0.0], 'led_red_2m'),
        ]:
            actor = actors[key]
            self.assertEqual(actor['components'], green['components'])
            self.assertEqual(actor['mesh'], 'LED_Strips_50cm')
            self.assertEqual(actor['sourceActor'], source)
            self.assertEqual(actor['color'], color)
            self.assertEqual(len(actor['lights']), 1)
            light = actor['lights'][0]
            self.assertEqual(light['color'], color)
            self.assertEqual(light['width'], 2.0)
            self.assertEqual(light['height'], 0.05)
            self.assertEqual(light['intensity'], 16.0)
            self.assertEqual(light['attenuationRadius'], 2.0)


    def test_fifty_cm_green_and_red_variants_are_catalogued(self):
        catalog_path = Path(__file__).parents[2] / 'site' / 'attachments' / 'catalog.json'
        actors = json.loads(catalog_path.read_text())['actors']
        blue = actors['Attachment_LED_Strip_04']
        for key, color, source in [
            ('Attachment_LED_Strip_05', [0.0, 1.0, 0.0], 'led_green_50cm'),
            ('Attachment_LED_Strip_06', [1.0, 0.0, 0.0], 'led_red_50cm'),
        ]:
            actor = actors[key]
            self.assertEqual(actor['components'], blue['components'])
            self.assertEqual(actor['mesh'], 'LED_Strips_50cm')
            self.assertEqual(actor['sourceActor'], source)
            self.assertEqual(actor['color'], color)
            self.assertEqual(len(actor['lights']), 1)
            light = actor['lights'][0]
            self.assertEqual(light['color'], color)
            self.assertEqual(light['width'], 0.5)
            self.assertEqual(light['height'], 0.05)
            self.assertEqual(light['intensity'], 19.199999)
            self.assertEqual(light['attenuationRadius'], 1.5)


    def test_all_vanilla_light_and_oversize_actors_have_assets(self):
        root = Path(__file__).parents[2] / 'site' / 'attachments'
        actors = json.loads((root / 'catalog.json').read_text())['actors']
        materials = json.loads((root / 'materials.json').read_text())
        keys = [f'Attachment_Light_{i:02d}' for i in range(1, 16)]
        keys += [
            'Attachment_OversizeLoad_PanelSign_Left',
            'Attachment_OversizeLoad_PanelSign_Right',
            *[f'Attachment_OversizeLoad_Sign_{i}' for i in range(1, 8)],
        ]
        self.assertEqual(len(keys), 24)
        for key in keys:
            with self.subTest(key=key):
                actor = actors[key]
                self.assertTrue(actor['components'])
                for component in actor['components']:
                    mesh = component['mesh']
                    self.assertTrue((root / 'glb' / f'{mesh}.glb').stat().st_size > 0)
                    defs = materials['materialsByMesh'][mesh]
                    self.assertTrue(defs)
                    for definition in defs.values():
                        self.assertIn('baseColor', definition)
                        if 'map' in definition:
                            texture = root / 'textures' / Path(definition['map']).name
                            self.assertTrue(texture.is_file(), texture)
                for light in actor['lights']:
                    self.assertEqual(light['type'], 'spot')
                    self.assertGreaterEqual(light['intensity'], 0)

        self.assertEqual(
            {component['mesh'] for component in actors['Attachment_Light_06']['components']},
            {'RotatingAmberLight_01_Case', 'RotatingAmberLight_01_Light'},
        )
        self.assertEqual(
            {component['mesh'] for component in actors['Attachment_Light_08']['components']},
            {'RotatingEmergencyLight_01_Case', 'RotatingEmergencyLight_01_Light'},
        )
        self.assertEqual(
            actors['Attachment_Light_01']['components'][0]['materialSlots'],
            ['M_Palette', 'MI_M_AttachmentLight_A6A6A6'],
        )
        sign = materials['materialsByMesh']['Sign_1']['Sign']
        self.assertTrue(sign['map'].endswith('/T_Signs_T_Signs.png'))


if __name__ == '__main__':
    unittest.main()
