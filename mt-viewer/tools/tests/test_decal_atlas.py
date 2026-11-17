import json
import subprocess
import unittest
from pathlib import Path


class DecalAtlasTests(unittest.TestCase):
    def test_canvas_sampling_inverts_only_image_v(self):
        module = Path(__file__).parents[2] / 'site' / 'js' / 'decal-projection.js'
        script = f"import {{decalAtlasUv}} from 'file://{module}'; console.log(JSON.stringify([decalAtlasUv(0,[0.25,0]),decalAtlasUv(0,[0.25,1]),decalAtlasUv(8,[0.25,0]),decalAtlasUv(8,[0.25,1])]));"
        output = subprocess.check_output(['node', '--input-type=module', '-e', script], text=True)
        self.assertEqual(json.loads(output), [[0.03125, 1], [0.03125, 0.875], [0.03125, 0.875], [0.03125, 0.75]])

    def test_primary_and_mirror_share_v_corrected_sampler(self):
        root = Path(__file__).parents[2] / 'site'
        index = (root / 'index.html').read_text()
        shader = (root / 'js' / 'decal-projection.js').read_text()
        self.assertIn('mtDecalAtlasUv(col, row, q);', index)
        self.assertIn('mtDecalAtlasUv(col, row, qm);', index)
        self.assertNotIn('((7.0-row)+q.y)', index)
        self.assertNotIn('((7.0-row)+qm.y)', index)
        self.assertIn('((7.0-row)+(1.0-q.y))', shader)


if __name__ == '__main__':
    unittest.main()
