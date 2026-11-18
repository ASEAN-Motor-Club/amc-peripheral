#!/usr/bin/env python3
"""png_sample.py — minimal PNG (8-bit RGB/RGBA) reader + UV sampler for atlas checks.

usage: png_sample.py <png> u1,v1 [u2,v2 ...]
prints the pixel at each normalised UV (glTF convention: v=0 is the TOP of the image,
i.e. row 0, matching how three.js samples with flipY=false).
"""
import struct
import sys
import zlib


def read_png(path):
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ihdr = 8, b"", None
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        typ = d[pos + 4:pos + 8]
        data = d[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", data)
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
    w, h, bd, ct = ihdr[0], ihdr[1], ihdr[2], ihdr[3]
    assert bd == 8, f"bit depth {bd} unsupported"
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(idat)
    stride = w * ch
    rows, prev, off = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        off += 1 + stride
        if ft == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        rows.append(bytes(line))
        prev = line
    return w, h, ch, rows


def main():
    path = sys.argv[1]
    w, h, ch, rows = read_png(path)
    print(f"{path}: {w}x{h} ch={ch}")
    for arg in sys.argv[2:]:
        u, v = (float(x) for x in arg.split(","))
        x = min(w - 1, max(0, int(u * w)))
        y = min(h - 1, max(0, int(v * h)))
        px = rows[y][x * ch:(x + 1) * ch]
        print(f"  uv({u:.3f},{v:.3f}) -> ({x},{y}) rgba={list(px)}")


if __name__ == "__main__":
    main()
