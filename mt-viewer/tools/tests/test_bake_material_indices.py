import json
import tempfile
import unittest
from pathlib import Path

from tools.bake_materials import body_material_entries, main as bake_materials


class BodyMaterialIndexTests(unittest.TestCase):
    def test_ordered_list_preserves_duplicate_asset_positions(self):
        rows = {'M_Body': {'material': 'M_Body'}, 'Race': {'material': 'Race'}}
        with tempfile.TemporaryDirectory() as td:
            Path(td, 'body_materials.json').write_text(json.dumps(['Race', 'M_Body', 'M_Body']))
            entries = body_material_entries(td, rows)
        self.assertEqual([raw for raw, _ in entries], ['Race', 'M_Body', 'M_Body'])
        self.assertEqual([index for index, _ in enumerate(entries)], [0, 1, 2])
        self.assertIsNotNone(entries[2][1])
        self.assertEqual(entries[2][1]['material'], 'M_Body')

    def test_bake_preserves_missing_materials_at_authored_indices(self):
        with tempfile.TemporaryDirectory() as td:
            build = Path(td, 'build'); build.mkdir()
            out = Path(td, 'out')
            (build / 'mesh_materials.json').write_text(json.dumps({
                '__materials__': {'Race': {'material': 'Race', 'colors': {}}},
            }))
            (build / 'body_materials.json').write_text(json.dumps(['Race', 'Missing', 'Missing']))
            bake_materials(str(build), str(out))
            variants = json.loads((out / 'materials.json').read_text())['bodyVariants']
        self.assertEqual([v['index'] for v in variants], [0, 1, 2])
        self.assertEqual([v['materialName'] for v in variants], ['Race', 'Missing', 'Missing'])


if __name__ == '__main__':
    unittest.main()
