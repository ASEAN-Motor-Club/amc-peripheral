import json
import tempfile
import unittest
from pathlib import Path

from tools import glb_slots


class GlbSlotRewriteTests(unittest.TestCase):
    def write_glb(self, root, document):
        raw = json.dumps(document).encode()
        raw += b' ' * ((4 - len(raw) % 4) % 4)
        blob = b'glTF' + (2).to_bytes(4, 'little') + (20 + len(raw)).to_bytes(4, 'little')
        blob += len(raw).to_bytes(4, 'little') + b'JSON' + raw
        path = root / 'in.glb'
        path.write_bytes(blob)
        return path

    def read_materials(self, path):
        data = path.read_bytes()
        size = int.from_bytes(data[12:16], 'little')
        return json.loads(data[20:20 + size])['materials']

    def test_repeated_palette_primitives_reuse_unique_slot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.write_glb(root, {
                'materials': [{'name': 'M_Palette'}, {'name': 'M_Body'}],
                'meshes': [{'primitives': [
                    {'material': 0}, {'material': 0}, {'material': 1},
                ]}],
            })
            output = root / 'out.glb'
            glb_slots.rewrite(source, output, [('Palette', 'M_Palette'), ('Seat_01', 'M_Body')])
            self.assertEqual([m['name'] for m in self.read_materials(output)],
                             ['Palette', 'Palette', 'Seat_01'])

    def test_distinct_slots_sharing_asset_keep_sequence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.write_glb(root, {
                'materials': [{'name': 'M_Body'}],
                'meshes': [{'primitives': [{'material': 0}, {'material': 0}]}],
            })
            output = root / 'out.glb'
            glb_slots.rewrite(source, output, [('Body_01', 'M_Body'), ('Seat_01', 'M_Body')])
            self.assertEqual([m['name'] for m in self.read_materials(output)],
                             ['Body_01', 'Seat_01'])
    def test_section_triangle_counts_survive_primitive_reordering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.write_glb(root, {
                'materials': [{'name': 'M_Body'}],
                'accessors': [{'count': 30}, {'count': 60}, {'count': 90}],
                'meshes': [{'primitives': [
                    {'material': 0, 'indices': 0},
                    {'material': 0, 'indices': 1},
                    {'material': 0, 'indices': 2},
                ]}],
            })
            output = root / 'out.glb'
            glb_slots.rewrite(source, output,
                              [('Body_01', 'MotorTown/Content/Cars/Materials/Body/M_Body.M_Body'),
                               ('Seat_01', 'MotorTown/Content/Cars/Materials/Body/M_Body.M_Body'),
                               ('Seat_02', 'MotorTown/Content/Cars/Materials/Body/M_Body.M_Body')],
                              [{'slot': 'Seat_01', 'triangles': 30},
                               {'slot': 'Seat_02', 'triangles': 20},
                               {'slot': 'Body_01', 'triangles': 10}])
            self.assertEqual([m['name'] for m in self.read_materials(output)],
                             ['Body_01', 'Seat_02', 'Seat_01'])

    def test_authoritative_sections_resolve_duplicate_assets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.write_glb(root, {
                'materials': [{'name': 'M_Body'}],
                'meshes': [{'primitives': [{'material': 0}, {'material': 0}, {'material': 0}]}],
            })
            output = root / 'out.glb'
            glb_slots.rewrite(source, output,
                              [('Body_01', 'MotorTown/Content/Cars/Materials/Body/M_Body.M_Body'),
                               ('Seat_01', 'MotorTown/Content/Cars/Materials/Body/M_Body.M_Body'),
                               ('Seat_02', 'MotorTown/Content/Cars/Materials/Body/M_Body.M_Body')],
                              ['Seat_01', 'Seat_02', 'Body_01'])
            self.assertEqual([m['name'] for m in self.read_materials(output)],
                             ['Seat_01', 'Seat_02', 'Body_01'])


if __name__ == '__main__':
    unittest.main()
