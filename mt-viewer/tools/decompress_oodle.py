#!/usr/bin/env python3
"""Decompress UE shader blobs with Oodle and carve their DXBC containers."""

import argparse
import ctypes
import functools
import json
import struct
from pathlib import Path


@functools.lru_cache(maxsize=4)
def load_oodle(path):
    lib = ctypes.CDLL(path)
    fn = lib.OodleLZ_Decompress
    fn.restype = ctypes.c_int
    fn.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
    ]
    return fn


def decompress_shader(compressed, uncompressed_size, oodle_path):
    """Return exactly uncompressed_size bytes or raise on a short/failed decode."""
    output = ctypes.create_string_buffer(uncompressed_size)
    result = load_oodle(oodle_path)(
        compressed, len(compressed), output, uncompressed_size,
        1, 0, 0, None, 0, None, None, None, 0, 3,
    )
    if result < 0:
        raise ValueError(f'OodleLZ_Decompress failed with code {result}')
    if result != uncompressed_size:
        raise ValueError(f'Oodle returned {result} bytes, expected {uncompressed_size}')
    return output.raw


def carve_dxbc(raw):
    """Locate and structurally validate a complete DXBC container in a UE shader."""
    start = raw.find(b'DXBC')
    if start < 0:
        raise ValueError('DXBC magic not found in decompressed shader')
    if start + 32 > len(raw):
        raise ValueError('truncated DXBC header')
    version, total_size, chunk_count = struct.unpack_from('<III', raw, start + 20)
    if version != 1:
        raise ValueError(f'unsupported DXBC version {version}')
    end = start + total_size
    if total_size < 32 or end > len(raw):
        raise ValueError('DXBC container size outside decompressed shader')
    if 32 + 4*chunk_count > total_size:
        raise ValueError('DXBC chunk offset table outside container')
    offsets = struct.unpack_from('<' + 'I' * chunk_count, raw, start + 32)
    for offset in offsets:
        if offset < 32 or offset + 8 > total_size:
            raise ValueError('DXBC chunk offset outside container')
        chunk_size = struct.unpack_from('<I', raw, start + offset + 4)[0]
        if offset + 8 + chunk_size > total_size:
            raise ValueError('DXBC chunk extends outside container')
    return raw[start:end]


def extract_dxbc(input_path, uncompressed_size, out_dir, oodle_path):
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = decompress_shader(input_path.read_bytes(), uncompressed_size, oodle_path)
    container = carve_dxbc(raw)
    name = input_path.name.split('.')[0]
    raw_path = out_dir / f'{name}.raw'
    dxbc_path = out_dir / f'{name}.dxbc'
    raw_path.write_bytes(raw)
    dxbc_path.write_bytes(container)
    return {
        'index': int(name),
        'raw_size': len(raw),
        'dxbc_offset': raw.find(b'DXBC'),
        'dxbc_size': len(container),
        'raw_path': str(raw_path),
        'dxbc_path': str(dxbc_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path, help='manifest.json from extract_decal_shaders.py')
    parser.add_argument('--oodle', required=True, help='path to the Oodle shared library')
    parser.add_argument('--out', type=Path, help='output directory (default: beside the inputs)')
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    out_dir = args.out or args.manifest.parent
    results = [extract_dxbc(Path(s['path']), s['uncompressed_size'], out_dir, args.oodle)
               for s in manifest['shaders']]
    report = out_dir / 'decompression.json'
    report.write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
