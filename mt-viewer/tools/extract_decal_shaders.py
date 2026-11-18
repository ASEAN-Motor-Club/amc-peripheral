#!/usr/bin/env python3
"""Extract a material's compressed shaders from a UE FShaderCodeArchive (version 2)."""

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShaderMapEntry:
    shader_indices_offset: int
    num_shaders: int
    first_preload_index: int
    num_preload_entries: int


@dataclass(frozen=True)
class ShaderCodeEntry:
    offset: int
    size: int
    uncompressed_size: int
    frequency: int


@dataclass(frozen=True)
class ShaderArchive:
    version: int
    map_hashes: list[bytes]
    shader_hashes: list[bytes]
    map_entries: list[ShaderMapEntry]
    shader_entries: list[ShaderCodeEntry]
    shader_indices: list[int]
    code_base: int
    data: bytes


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError('directory entry outside archive')
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))

    def count(self):
        return self.unpack('I')[0]

    def hashes(self):
        return [self.take(20) for _ in range(self.count())]


def parse_archive(data):
    """Parse the directory and validate every compressed shader byte range."""
    r = Reader(data)
    version = r.unpack('I')[0]
    if version != 2:
        raise ValueError(f'unsupported shader archive version {version}')
    map_hashes = r.hashes()
    shader_hashes = r.hashes()
    map_entries = [ShaderMapEntry(*r.unpack('4I')) for _ in range(r.count())]
    shader_entries = [ShaderCodeEntry(*r.unpack('QII B')) for _ in range(r.count())]
    # FFileCachePreloadEntry is two int64 values; its contents are not needed here.
    r.take(16 * r.count())
    index_count = r.count()
    shader_indices = list(struct.unpack('<' + 'I' * index_count, r.take(4 * index_count)))
    code_base = r.pos

    for index, entry in enumerate(shader_entries):
        if entry.offset + entry.size > len(data) - code_base:
            raise ValueError(f'shader {index} byte range outside archive')
    for index in shader_indices:
        if index >= len(shader_entries):
            raise ValueError(f'shader index {index} outside shader entry table')
    return ShaderArchive(version, map_hashes, shader_hashes, map_entries, shader_entries,
                         shader_indices, code_base, data)


def extract_material(data, material_hash, out_dir):
    archive = parse_archive(data)
    try:
        map_index = archive.map_hashes.index(material_hash)
    except ValueError as exc:
        raise ValueError('material hash not found in shader archive') from exc

    entry = archive.map_entries[map_index]
    start = entry.shader_indices_offset
    end = start + entry.num_shaders
    if end > len(archive.shader_indices):
        raise ValueError('shader map index range outside archive')
    # A map may reference a deduplicated shader more than once; write each unique shader once.
    shader_indices = list(dict.fromkeys(archive.shader_indices[start:end]))

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    shaders = []
    for index in shader_indices:
        shader = archive.shader_entries[index]
        absolute = archive.code_base + shader.offset
        path = output / f'{index}.compressed'
        path.write_bytes(data[absolute:absolute + shader.size])
        shaders.append({
            'index': index,
            'offset': shader.offset,
            'absolute_offset': absolute,
            'compressed_size': shader.size,
            'uncompressed_size': shader.uncompressed_size,
            'frequency': shader.frequency,
            'path': str(path),
        })
    manifest = {
        'archive_version': archive.version,
        'material_hash': material_hash.hex(),
        'map_index': map_index,
        'shader_indices_offset': entry.shader_indices_offset,
        'num_shaders': entry.num_shaders,
        'shader_indices': shader_indices,
        'code_base': archive.code_base,
        'shaders': shaders,
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('material_uexp', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()

    archive = parse_archive(args.archive.read_bytes())
    material = args.material_uexp.read_bytes()
    matches = [h for h in archive.map_hashes if h in material]
    if len(matches) != 1:
        raise SystemExit(f'expected exactly one material hash in {args.material_uexp}, got {len(matches)}')
    manifest = extract_material(archive.data, matches[0], args.output)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
