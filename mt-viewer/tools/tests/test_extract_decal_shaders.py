import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.extract_decal_shaders import extract_material, parse_archive


def array(payload, count=1):
    return struct.pack('<I', count) + payload


def make_archive(truncate=False):
    target_hash = bytes(range(20))
    shader_hash = bytes(range(20, 40))
    map_hashes = array(target_hash)
    shader_hashes = array(shader_hash)
    map_entries = array(struct.pack('<4I', 0, 1, 0, 1))
    shader_entries = array(struct.pack('<QII B', 0, 4, 9, 0))
    preload_entries = array(struct.pack('<qq', 0, 4))
    shader_indices = array(struct.pack('<I', 0))
    code = b'\x8c\x0a\x00\x00'
    blob = (struct.pack('<I', 2) + map_hashes + shader_hashes + map_entries +
            shader_entries + preload_entries + shader_indices + code)
    if truncate:
        blob = blob[:-1]
    return blob, target_hash


class ArchiveTests(unittest.TestCase):
    def test_parse_documented_layout(self):
        blob, _ = make_archive()
        archive = parse_archive(blob)
        self.assertEqual(archive.version, 2)
        self.assertEqual(archive.map_entries[0].shader_indices_offset, 0)
        self.assertEqual(archive.map_entries[0].num_shaders, 1)
        self.assertEqual(archive.shader_entries[0].uncompressed_size, 9)
        self.assertEqual(archive.shader_indices, [0])
        self.assertEqual(archive.code_base, len(blob) - 4)

    def test_extract_writes_compressed_blob_and_manifest(self):
        blob, target_hash = make_archive()
        with tempfile.TemporaryDirectory() as td:
            manifest = extract_material(blob, target_hash, td)
            self.assertEqual(manifest['map_index'], 0)
            self.assertEqual(manifest['shader_indices'], [0])
            self.assertEqual(manifest['shaders'][0]['compressed_size'], 4)
            self.assertEqual(manifest['shaders'][0]['uncompressed_size'], 9)
            self.assertEqual(Path(manifest['shaders'][0]['path']).read_bytes(), b'\x8c\x0a\x00\x00')
            self.assertEqual(json.loads((Path(td) / 'manifest.json').read_text()), manifest)

    def test_truncated_shader_payload_is_rejected(self):
        blob, target_hash = make_archive(truncate=True)
        with self.assertRaisesRegex(ValueError, 'outside archive'):
            parse_archive(blob)

    def test_unknown_material_hash_is_rejected(self):
        blob, _ = make_archive()
        with self.assertRaisesRegex(ValueError, 'material hash not found'):
            extract_material(blob, b'x' * 20, tempfile.mkdtemp())


@unittest.skipUnless(Path('/opt/data/workspace/mt-viewer/build/shader_archive_sm5.bin').exists(),
                     'real shader archive not present')
class RealArchiveTests(unittest.TestCase):
    def test_motor_town_decal_material_map(self):
        archive_path = Path('/opt/data/workspace/mt-viewer/build/shader_archive_sm5.bin')
        material_path = Path('/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/out/M_DecalBounds_Test.uexp')
        blob = archive_path.read_bytes()
        material = material_path.read_bytes()
        archive = parse_archive(blob)
        matches = [i for i, h in enumerate(archive.map_hashes) if h in material]
        self.assertEqual(matches, [266])
        with tempfile.TemporaryDirectory() as td:
            manifest = extract_material(blob, archive.map_hashes[266], td)
            self.assertEqual(manifest['shader_indices'], [5019, 5020, 5021])
            self.assertEqual([(s['compressed_size'], s['uncompressed_size']) for s in manifest['shaders']],
                             [(4119, 14442), (2775, 8273), (4120, 11951)])
            self.assertTrue(all(Path(s['path']).read_bytes().startswith(b'\x8c\x0a')
                                for s in manifest['shaders']))


if __name__ == '__main__':
    unittest.main()
