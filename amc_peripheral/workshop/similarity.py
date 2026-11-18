"""Decal-similarity index for workshop builds.

The workshop payload stores decals as vector placements (``decalLayers``), not
images, and the coordinates are vehicle-local. Two uploads that share decal work
therefore share numbers, which makes copy detection an exact, cheap comparison
rather than a rendering problem.

The index is precomputed into the site database (``similar_pair``) by a batch
job so the item page can read it with one indexed query. Scoring:

1. quantised fingerprints -> candidate pairs (inverted index)
2. weighted Gaussian layer kernel over (position, rotation, scale, stretch,
   colour, flags), same ``decalKey`` required
3. Dice coefficient over a maximum-weight layer assignment, so added or removed
   layers cost score proportionally instead of rounding to "identical"
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_MIN_SIM = 0.60
DEFAULT_MIN_LAYERS = 3
COPY_THRESHOLD = 0.95
GENERIC_FINGERPRINT = 400
CANDIDATE_MIN = 0.20

# kernel scales
S_POS = 120.0
S_ROT = 25.0
S_SCALE = 0.45
S_STRETCH = 0.45
S_COLOR = 90.0
TAU = 0.35

PUBLIC_WHERE = "deleted_at IS NULL AND COALESCE(hidden, 0) = 0 AND account_id > 0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS similar_pair (
    vehicle_key TEXT NOT NULL,
    a           INTEGER NOT NULL,
    b           INTEGER NOT NULL,
    sim         REAL    NOT NULL,
    created_a   TEXT    NOT NULL,
    created_b   TEXT    NOT NULL,
    PRIMARY KEY (vehicle_key, a, b)
);
CREATE INDEX IF NOT EXISTS ix_similar_a ON similar_pair(a, sim DESC);
CREATE INDEX IF NOT EXISTS ix_similar_b ON similar_pair(b, sim DESC);
CREATE TABLE IF NOT EXISTS similar_runs (
    run_id      INTEGER PRIMARY KEY,
    finished_at TEXT NOT NULL,
    vehicles    INTEGER NOT NULL,
    models      INTEGER NOT NULL,
    pairs       INTEGER NOT NULL,
    min_sim     REAL NOT NULL,
    min_layers  INTEGER NOT NULL
);
"""


# --------------------------------------------------------------------------- #
# layer model
# --------------------------------------------------------------------------- #

Layer = dict


def _layer(key, colour, x, y, pitch, yaw, roll, scale, stretch, flags) -> Layer:
    return {
        "key": key,
        "rgb": (int(colour[0]), int(colour[1]), int(colour[2])),
        "x": float(x or 0.0),
        "y": float(y or 0.0),
        "pitch": float(pitch or 0.0),
        "yaw": float(yaw or 0.0),
        "roll": float(roll or 0.0),
        "scale": float(scale if scale is not None else 1.0),
        "stretch": float(stretch if stretch is not None else 1.0),
        "flags": int(flags or 0),
    }


def _layers_from_payload(blob: bytes) -> list[Layer]:
    try:
        data = json.loads(zlib.decompress(blob))
    except (zlib.error, ValueError, TypeError):
        return []
    decal = ((data.get("decal") or {}).get("decal") or {}) if isinstance(data, dict) else {}
    out = []
    for raw in decal.get("decalLayers") or []:
        if not isinstance(raw, dict):
            continue
        colour = raw.get("color") or {}
        position = raw.get("position") or {}
        rotation = raw.get("rotation") or {}
        out.append(_layer(
            raw.get("decalKey") or "",
            (colour.get("r"), colour.get("g"), colour.get("b")),
            position.get("x"), position.get("y"),
            rotation.get("pitch"), rotation.get("yaw"), rotation.get("roll"),
            raw.get("decalScale"), raw.get("stretch"), raw.get("flags"),
        ))
    return out


def load_vehicle_layers(
    conn: sqlite3.Connection, vehicle_key: str
) -> tuple[dict[int, list[Layer]], dict[int, tuple[int, str]]]:
    """Return ``{workshop_id: layers}`` plus ``{workshop_id: (account_id, created_at)}``."""
    meta: dict[int, tuple[int, str]] = {}
    for wid, account, created, layer_count in conn.execute(
        f"SELECT id, account_id, created_at, decal_layers FROM workshop "
        f"WHERE vehicle_key = ? AND {PUBLIC_WHERE}",
        (vehicle_key,),
    ):
        if int(layer_count or 0) <= 0:
            continue
        meta[int(wid)] = (int(account), str(created or ""))
    if not meta:
        return {}, {}

    have_children = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workshop_decal_layer'"
    ).fetchone()
    layers: dict[int, list[Layer]] = defaultdict(list)
    if have_children:
        for wid, key, r, g, b, x, y, pitch, yaw, roll, scale, stretch, flags in conn.execute(
            "SELECT workshop_id, decal_key, r, g, b, x, y, pitch, yaw, roll, "
            "scale, stretch, flags FROM workshop_decal_layer "
            "WHERE workshop_id IN (SELECT id FROM workshop WHERE vehicle_key = ? "
            f"AND {PUBLIC_WHERE}) ORDER BY workshop_id, idx",
            (vehicle_key,),
        ):
            if int(wid) in meta:
                layers[int(wid)].append(
                    _layer(key, (r, g, b), x, y, pitch, yaw, roll, scale, stretch, flags)
                )
    else:
        for wid, blob in conn.execute(
            f"SELECT id, json_z FROM workshop WHERE vehicle_key = ? AND {PUBLIC_WHERE}",
            (vehicle_key,),
        ):
            if int(wid) in meta and blob:
                layers[int(wid)] = _layers_from_payload(blob)
    return {k: v for k, v in layers.items() if k in meta}, meta


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #

def angle_delta(a: float, b: float, mod: float = 360.0) -> float:
    diff = abs((a - b) % mod)
    return min(diff, mod - diff)


def layer_distance(a: Layer, b: Layer) -> float:
    dpos = math.hypot(a["x"] - b["x"], a["y"] - b["y"]) / S_POS
    dyaw = angle_delta(a["yaw"], b["yaw"]) / S_ROT
    droll = angle_delta(a["roll"], b["roll"]) / S_ROT
    dpitch = angle_delta(a["pitch"], b["pitch"]) / S_ROT
    dscale = abs(math.log(max(a["scale"], 1e-4) / max(b["scale"], 1e-4))) / S_SCALE
    dstretch = abs(math.log(max(a["stretch"], 1e-4) / max(b["stretch"], 1e-4))) / S_STRETCH
    dcolor = math.dist(a["rgb"], b["rgb"]) / S_COLOR
    dflags = 0.0 if a["flags"] == b["flags"] else 0.5
    return (
        0.34 * dpos ** 2
        + 0.12 * dyaw ** 2
        + 0.16 * droll ** 2
        + 0.04 * dpitch ** 2
        + 0.12 * dscale ** 2
        + 0.10 * dstretch ** 2
        + 0.09 * dcolor ** 2
        + 0.03 * dflags ** 2
    ) ** 0.5


def layer_similarity(a: Layer, b: Layer) -> float:
    distance = layer_distance(a, b)
    if distance >= 1.2:
        return 0.0
    return math.exp(-((distance / TAU) ** 2))


def fingerprint(layer: Layer, pos: float = 25.0, ang: float = 10.0, scale: float = 8.0):
    return (
        layer["key"],
        round(layer["x"] / pos), round(layer["y"] / pos),
        round(layer["yaw"] / ang) % 36, round(layer["roll"] / ang) % 36,
        round(layer["scale"] * scale), round(layer["stretch"] * scale),
        layer["flags"],
    )


def greedy_dice(a_layers: list[Layer], b_layers: list[Layer], gate: float = 0.05) -> float:
    """Unique-assignment greedy Dice — the cheap score used for pruning."""
    if not a_layers or not b_layers:
        return 0.0
    by_key: dict[str, list[tuple[int, Layer]]] = defaultdict(list)
    for index, layer in enumerate(b_layers):
        by_key[layer["key"]].append((index, layer))
    pairs = []
    for index, layer in enumerate(a_layers):
        for other_index, other in by_key.get(layer["key"], ()):
            score = layer_similarity(layer, other)
            if score > gate:
                pairs.append((score, index, other_index))
    pairs.sort(reverse=True)
    used_a, used_b, total = set(), set(), 0.0
    for score, index, other_index in pairs:
        if index in used_a or other_index in used_b:
            continue
        used_a.add(index)
        used_b.add(other_index)
        total += score
    return 2.0 * total / (len(a_layers) + len(b_layers))


def matched_similarity(a_layers: list[Layer], b_layers: list[Layer]) -> float:
    """Dice coefficient over a maximum-weight bipartite layer assignment."""
    if not a_layers or not b_layers:
        return 0.0
    size = max(len(a_layers), len(b_layers))
    weights = [[0.0] * size for _ in range(size)]
    for i, layer in enumerate(a_layers):
        for j, other in enumerate(b_layers):
            if layer["key"] == other["key"]:
                weights[i][j] = layer_similarity(layer, other)
    assignment = _hungarian(weights, size)
    total = sum(
        weights[i][j] for i, j in assignment
        if i < len(a_layers) and j < len(b_layers) and weights[i][j] > 0.02
    )
    return 2.0 * total / (len(a_layers) + len(b_layers))


def _hungarian(weights: list[list[float]], size: int) -> list[tuple[int, int]]:
    """Maximum-weight assignment (Kuhn–Munkres with potentials)."""
    cost = [[-weights[i][j] for j in range(size)] for i in range(size)]
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if current < minv[j]:
                    minv[j] = current
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return [(p[j] - 1, j - 1) for j in range(1, size + 1) if p[j]]


def pair_similarity(a_layers: list[Layer], b_layers: list[Layer]) -> float:
    return matched_similarity(a_layers, b_layers)


# --------------------------------------------------------------------------- #
# index build
# --------------------------------------------------------------------------- #

def scan_vehicle(
    conn: sqlite3.Connection,
    vehicle_key: str,
    *,
    min_sim: float = DEFAULT_MIN_SIM,
    min_layers: int = DEFAULT_MIN_LAYERS,
) -> list[tuple[str, int, int, float, str, str]]:
    layers, meta = load_vehicle_layers(conn, vehicle_key)
    ids = [wid for wid in sorted(layers) if len(layers[wid]) >= min_layers]
    if len(ids) < 2:
        return []

    fingerprints = {wid: {fingerprint(layer) for layer in layers[wid]} for wid in ids}
    index: dict[tuple, list[int]] = defaultdict(list)
    for wid in ids:
        for value in fingerprints[wid]:
            index[value].append(wid)
    candidates: dict[tuple[int, int], int] = defaultdict(int)
    for members in index.values():
        if len(members) < 2 or len(members) > GENERIC_FINGERPRINT:
            continue
        for first in range(len(members)):
            for second in range(first + 1, len(members)):
                candidates[(members[first], members[second])] += 1

    rows: list[tuple[str, int, int, float, str, str]] = []
    for (left, right), _shared in candidates.items():
        if greedy_dice(layers[left], layers[right]) < CANDIDATE_MIN:
            continue
        score = pair_similarity(layers[left], layers[right])
        if score < min_sim:
            continue
        a, b = (left, right) if left < right else (right, left)
        rows.append((vehicle_key, a, b, round(score, 4),
                     meta[a][1], meta[b][1]))
    return rows


def build(
    source_db: Path,
    site_db: Path,
    *,
    vehicles: Iterable[str] | None = None,
    min_sim: float = DEFAULT_MIN_SIM,
    min_layers: int = DEFAULT_MIN_LAYERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Recompute the similarity index in ``site_db`` from ``source_db``."""
    say = progress or (lambda message: None)
    site_db.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(site_db, timeout=30.0)
    out.executescript(SCHEMA)
    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=10.0)

    if vehicles is None:
        targets = [
            row[0]
            for row in source.execute(
                "SELECT vehicle_key FROM workshop "
                f"WHERE {PUBLIC_WHERE} GROUP BY vehicle_key"
            )
        ]
    else:
        targets = [str(v) for v in vehicles]

    started = time.time()
    total_pairs = 0
    models = 0
    for position, vehicle in enumerate(targets, 1):
        rows = scan_vehicle(source, vehicle, min_sim=min_sim, min_layers=min_layers)
        out.execute("DELETE FROM similar_pair WHERE vehicle_key = ?", (vehicle,))
        out.executemany(
            "INSERT OR REPLACE INTO similar_pair "
            "(vehicle_key, a, b, sim, created_a, created_b) VALUES (?,?,?,?,?,?)",
            rows,
        )
        out.commit()
        total_pairs += len(rows)
        models += 1
        say(
            f"[{position}/{len(targets)}] {vehicle}: {len(rows)} pairs"
            f" ({time.time() - started:.0f}s)"
        )
    out.execute(
        "INSERT INTO similar_runs (finished_at, vehicles, models, pairs, min_sim, min_layers)"
        " VALUES (?,?,?,?,?,?)",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), len(targets), models,
         total_pairs, min_sim, min_layers),
    )
    out.commit()
    out.close()
    source.close()
    return {"vehicles": len(targets), "pairs": total_pairs}


def main(argv: list[str] | None = None) -> int:
    from .config import WorkshopSettings

    parser = argparse.ArgumentParser(description="Build the workshop decal-similarity index")
    parser.add_argument("--source", type=Path, help="workshop.db (read-only); defaults to AMC_WORKSHOP_DB")
    parser.add_argument("--site", type=Path, help="site database to write; defaults to AMC_WORKSHOP_SITE_DB")
    parser.add_argument("--vehicle", action="append", help="limit to a vehicle key (repeatable)")
    parser.add_argument("--min-sim", type=float, default=DEFAULT_MIN_SIM)
    parser.add_argument("--min-layers", type=int, default=DEFAULT_MIN_LAYERS)
    args = parser.parse_args(argv)
    source = args.source
    site = args.site
    if source is None or site is None:
        settings = WorkshopSettings.from_env()
        source = source or settings.source_db
        site = site or settings.site_db
    result = build(
        source, site, vehicles=args.vehicle,
        min_sim=args.min_sim, min_layers=args.min_layers,
        progress=lambda message: print(message, flush=True),
    )
    print(f"indexed {result['pairs']} pairs across {result['vehicles']} vehicles")
    return 0


def cli() -> None:
    """Console entry point (``amc_workshop_similarity``)."""
    raise SystemExit(main())


if __name__ == "__main__":
    sys.exit(main())
