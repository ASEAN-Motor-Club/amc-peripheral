import unittest
from pathlib import Path


class StreamingPerformanceSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (Path(__file__).parents[2] / 'site' / 'index.html').read_text()

    def test_meshopt_preview_is_loaded_before_full_part_completion(self):
        self.assertIn('loader.setMeshoptDecoder(MeshoptDecoder)', self.index)
        self.assertIn('manifest.preview?.glb', self.index)
        self.assertIn('loadTiming.preview', self.index)
        self.assertIn('if (fullPartsAdded)', self.index)
        self.assertIn('root.remove(previewModel)', self.index)

    def test_dynamic_lights_default_to_four_with_full_diagnostic_mode(self):
        self.assertIn('params.get("attachmentLights") === "full" ? 24 : 4', self.index)
        self.assertIn('if (info.lights >= lightBudget)', self.index)

    def test_attachment_stage_has_no_redundant_full_scene_compile(self):
        start = self.index.index('async function streamAttachments()')
        end = self.index.index('// --- base materials', start)
        stage = self.index[start:end]
        self.assertNotIn('compileAsync', stage)
        self.assertNotIn('render();', stage)
    def test_decal_eligibility_uses_slots_not_mesh_heuristics(self):
        source = self.index
        self.assertIn('eligibleSlots.has(m.name)', source)
        self.assertIn('decalFallbackSlots(slots, slotDefs, bodyVariants, liveryIndex)', source)
        self.assertNotIn('const minSpan', source)
        self.assertNotIn('o.geometry.attributes.uv1', source)
        self.assertNotIn('const shellName', source)

    def test_single_subtle_environment_for_metals(self):
        source = self.index
        self.assertIn('new THREE.PMREMGenerator(renderer)', source)
        self.assertIn('new RoomEnvironment()', source)
        self.assertIn('scene.environmentIntensity = 0.45', source)
        self.assertEqual(source.count('pmrem.fromScene('), 1)


if __name__ == '__main__':
    unittest.main()
