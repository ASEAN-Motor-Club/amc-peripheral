import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.decompress_oodle import carve_dxbc, decompress_shader, extract_dxbc


OODLE = '/opt/data/cache/scratch/rp/liboo2corelinux64.so.9'
ARCHIVE_ROOT = Path('/opt/data/workspace/mt-viewer')
SHADERS = ARCHIVE_ROOT / 'build/decal_shaders'


def minimal_dxbc(payload=b'abcd'):
    chunk = b'TEST' + struct.pack('<I', len(payload)) + payload
    total = 32 + 4 + len(chunk)
    return (b'DXBC' + b'\0' * 16 + struct.pack('<III', 1, total, 1) +
            struct.pack('<I', 36) + chunk)


class DxbcTests(unittest.TestCase):
    def test_carves_container_from_ue_shader_wrapper(self):
        container = minimal_dxbc()
        self.assertEqual(carve_dxbc(b'prefix' + container + b'suffix'), container)

    def test_rejects_missing_magic(self):
        with self.assertRaisesRegex(ValueError, 'DXBC magic not found'):
            carve_dxbc(b'not a shader')

    def test_rejects_unsupported_version(self):
        data = bytearray(minimal_dxbc())
        struct.pack_into('<I', data, 20, 2)
        with self.assertRaisesRegex(ValueError, 'unsupported DXBC version'):
            carve_dxbc(data)

    def test_rejects_truncated_chunk_offset_table(self):
        data = bytearray(minimal_dxbc())
        struct.pack_into('<I', data, 28, 1000000)
        with self.assertRaisesRegex(ValueError, 'chunk offset table outside container'):
            carve_dxbc(data)

    def test_rejects_chunk_offset_inside_header(self):
        data = bytearray(minimal_dxbc())
        struct.pack_into('<I', data, 32, 0)
        with self.assertRaisesRegex(ValueError, 'chunk offset outside container'):
            carve_dxbc(data)

    def test_rejects_truncated_container(self):
        data = bytearray(minimal_dxbc())
        struct.pack_into('<I', data, 24, len(data) + 100)
        with self.assertRaisesRegex(ValueError, 'outside decompressed shader'):
            carve_dxbc(data)


@unittest.skipUnless(Path(OODLE).exists() and (SHADERS / 'manifest.json').exists(),
                     'Oodle library or extracted shader inputs not present')
class RealOodleTests(unittest.TestCase):
    def test_decompresses_and_carves_all_decal_shaders(self):
        manifest = json.loads((SHADERS / 'manifest.json').read_text())
        expected_ends = {5019: 14236, 5020: 8116, 5021: 11748}
        with tempfile.TemporaryDirectory() as td:
            for shader in manifest['shaders']:
                index = shader['index']
                compressed_path = ARCHIVE_ROOT / shader['path']
                raw = decompress_shader(compressed_path.read_bytes(),
                                        shader['uncompressed_size'], OODLE)
                self.assertEqual(len(raw), shader['uncompressed_size'])
                container = carve_dxbc(raw)
                self.assertEqual(struct.unpack_from('<I', container, 20)[0], 1)
                self.assertEqual(struct.unpack_from('<I', container, 28)[0], 3)
                self.assertEqual(raw.find(b'DXBC') + len(container), expected_ends[index])
                outputs = extract_dxbc(compressed_path, shader['uncompressed_size'],
                                       Path(td), OODLE)
                self.assertEqual(Path(outputs['raw_path']).read_bytes(), raw)
                self.assertEqual(Path(outputs['dxbc_path']).read_bytes(), container)


if __name__ == '__main__':
    unittest.main()
