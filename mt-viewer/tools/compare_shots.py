#!/usr/bin/env python3
"""compare_shots.py — numeric evidence that materials/textures are actually applied.

Decodes two PNG screenshots and reports:
  * mean absolute per-pixel difference and the fraction of pixels that changed
  * mean RGB per image over the "model" pixels (anything brighter than the
    background/grid), so a textured render can be told from a flat-grey one
  * the same stats restricted to a horizontal band (default: the lower third,
    i.e. wheels/tyres) so a material swap on one part is visible in the numbers

usage: compare_shots.py <a.png> <b.png> [band_lo band_hi]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from png_sample import read_png


def load(path):
    w, h, ch, rows = read_png(path)
    px = []
    for r in rows:
        px.append([tuple(r[i * ch:i * ch + 3]) for i in range(w)])
    return w, h, px


def stats(w, h, px, y0, y1):
    tot = [0, 0, 0]
    n = 0
    bright = 0
    for y in range(y0, y1):
        row = px[y]
        for (r, g, b) in row:
            if r + g + b < 90:      # background/grid
                continue
            bright += 1
            tot[0] += r
            tot[1] += g
            tot[2] += b
            n += 1
    if not n:
        return (0, 0, 0), 0
    return tuple(v / n for v in tot), bright


def diff(w, h, a, b, y0, y1):
    changed = 0
    total = 0
    acc = 0
    for y in range(y0, y1):
        ra, rb = a[y], b[y]
        for x in range(w):
            pa, pb = ra[x], rb[x]
            d = abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2])
            acc += d
            if d > 24:
                changed += 1
            total += 1
    return acc / max(1, total), changed / max(1, total)


def main():
    a_path, b_path = sys.argv[1], sys.argv[2]
    w, h, A = load(a_path)
    w2, h2, B = load(b_path)
    assert (w, h) == (w2, h2), "screenshots differ in size"
    lo = int(float(sys.argv[3]) * h) if len(sys.argv) > 3 else int(h * 0.62)
    hi = int(float(sys.argv[4]) * h) if len(sys.argv) > 4 else h

    print(f"A = {os.path.basename(a_path)}")
    print(f"B = {os.path.basename(b_path)}")
    for label, img in (("A", A), ("B", B)):
        (mr, mg, mb), nb = stats(w, h, img, lo, hi)
        print(f"  {label} band[{lo}:{hi}] mean rgb = ({mr:.0f},{mg:.0f},{mb:.0f})  lit px = {nb}")
    mad, frac = diff(w, h, A, B, lo, hi)
    print(f"  mean |diff| = {mad:.2f}/765   changed pixels = {frac*100:.1f}%  in band")
    mad_all, frac_all = diff(w, h, A, B, 0, h)
    print(f"  whole image: mean |diff| = {mad_all:.2f}/765  changed = {frac_all*100:.1f}%")


if __name__ == "__main__":
    main()
