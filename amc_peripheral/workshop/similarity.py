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
import os
import sqlite3
import sys
import time
import zlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_MIN_SIM = 0.60
DEFAULT_MIN_LAYERS = 3
COPY_THRESHOLD = 0.95
GENERIC_FINGERPRINT = 400
RARE_TOKEN_MIN = 2
RARE_TOKEN_MAX = 50
CANDIDATE_MIN = 0.40
INDEX_VERSION = 4

# kernel scales
S_POS = 120.0
S_ROT = 25.0
S_SCALE = 0.45
S_STRETCH = 0.45
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
CREATE TABLE IF NOT EXISTS similar_item (
    workshop_id INTEGER PRIMARY KEY,
    vehicle_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    layer_count INTEGER NOT NULL,
    indexed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_similar_item_vehicle
    ON similar_item(vehicle_key);
CREATE TABLE IF NOT EXISTS similar_runs (
    run_id      INTEGER PRIMARY KEY,
    finished_at TEXT NOT NULL,
    vehicles    INTEGER NOT NULL,
    models      INTEGER NOT NULL,
    pairs       INTEGER NOT NULL,
    min_sim     REAL NOT NULL,
    min_layers  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS similar_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# --------------------------------------------------------------------------- #
# layer model
# --------------------------------------------------------------------------- #

Layer = dict


def _layer(
    key,
    colour,
    x,
    y,
    pitch,
    yaw,
    roll,
    scale,
    stretch,
    flags,
    alpha: float | int | None = 255,
    coverage: float | int | None = 1.0,
) -> Layer:
    return {
        "key": key,
        "rgb": (int(colour[0]), int(colour[1]), int(colour[2])),
        "alpha": float(alpha if alpha is not None else 255),
        "coverage": float(coverage if coverage is not None else 1.0),
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
    decal = (
        ((data.get("decal") or {}).get("decal") or {}) if isinstance(data, dict) else {}
    )
    out = []
    for raw in decal.get("decalLayers") or []:
        if not isinstance(raw, dict):
            continue
        colour = raw.get("color") or {}
        position = raw.get("position") or {}
        rotation = raw.get("rotation") or {}
        out.append(
            _layer(
                raw.get("decalKey") or "",
                (colour.get("r"), colour.get("g"), colour.get("b")),
                position.get("x"),
                position.get("y"),
                rotation.get("pitch"),
                rotation.get("yaw"),
                rotation.get("roll"),
                raw.get("decalScale"),
                raw.get("stretch"),
                raw.get("flags"),
                colour.get("a"),
                raw.get("coverage"),
            )
        )
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
        for (
            wid,
            key,
            r,
            g,
            b,
            x,
            y,
            pitch,
            yaw,
            roll,
            scale,
            stretch,
            flags,
            alpha,
            coverage,
        ) in conn.execute(
            "SELECT workshop_id, decal_key, r, g, b, x, y, pitch, yaw, roll, "
            "scale, stretch, flags, a, coverage FROM workshop_decal_layer "
            "WHERE workshop_id IN (SELECT id FROM workshop WHERE vehicle_key = ? "
            f"AND {PUBLIC_WHERE}) ORDER BY workshop_id, idx",
            (vehicle_key,),
        ):
            if int(wid) in meta:
                layers[int(wid)].append(
                    _layer(
                        key,
                        (r, g, b),
                        x,
                        y,
                        pitch,
                        yaw,
                        roll,
                        scale,
                        stretch,
                        flags,
                        alpha,
                        coverage,
                    )
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
    dstretch = (
        abs(math.log(max(a["stretch"], 1e-4) / max(b["stretch"], 1e-4))) / S_STRETCH
    )
    dalpha = (
        abs(math.log(max(a.get("alpha", 255.0), 1.0) / max(b.get("alpha", 255.0), 1.0)))
        / 0.45
    )
    dcoverage = (
        abs(
            math.log(
                max(a.get("coverage", 1.0), 1e-3) / max(b.get("coverage", 1.0), 1e-3)
            )
        )
        / 0.45
    )
    dflags = 0.0 if a["flags"] == b["flags"] else 0.5
    return (
        0.32 * dpos**2
        + 0.12 * dyaw**2
        + 0.16 * droll**2
        + 0.04 * dpitch**2
        + 0.12 * dscale**2
        + 0.10 * dstretch**2
        + 0.02 * dalpha**2
        + 0.02 * dcoverage**2
        + 0.02 * dflags**2
    ) ** 0.5


def layer_similarity(a: Layer, b: Layer) -> float:
    distance = layer_distance(a, b)
    if distance >= 1.2:
        return 0.0
    return math.exp(-((distance / TAU) ** 2))


def fingerprint(layer: Layer, pos: float = 25.0, ang: float = 10.0, scale: float = 8.0):
    return (
        layer["key"],
        round(layer["x"] / pos),
        round(layer["y"] / pos),
        round(layer["yaw"] / ang) % 36,
        round(layer["roll"] / ang) % 36,
        round(layer["scale"] * scale),
        round(layer["stretch"] * scale),
        layer["flags"],
    )


# Pair-hash candidate generation (Wang 2003 style).  Every token is relative,
# so a global drag/rotate/scale keeps the same token; mirrored variants are
# indexed separately because `flags` is deliberately not in the token.
PAIR_FANOUT = 8
PAIR_POS = 25.0
PAIR_ANG = 10.0
PAIR_SCALE = 0.125
PAIR_MIN_SHARED = 3


def _pair_token(anchor: Layer, partner: Layer) -> tuple:
    dx = partner["x"] - anchor["x"]
    dy = partner["y"] - anchor["y"]
    dyaw = angle_delta(anchor["yaw"], partner["yaw"])
    droll = angle_delta(anchor["roll"], partner["roll"])
    dscl = math.log(max(partner["scale"], 1e-4) / max(anchor["scale"], 1e-4))
    dstr = math.log(max(partner["stretch"], 1e-4) / max(anchor["stretch"], 1e-4))
    return (
        anchor["key"],
        partner["key"],
        round(dx / PAIR_POS),
        round(dy / PAIR_POS),
        round(dyaw / PAIR_ANG) % 36,
        round(droll / PAIR_ANG) % 36,
        round(dscl / PAIR_SCALE),
        round(dstr / PAIR_SCALE),
    )


def _mirror_layer(layer: Layer) -> Layer:
    out = dict(layer)
    out["x"] = -out["x"]
    out["yaw"] = (-out["yaw"]) % 360.0
    out["roll"] = (-out["roll"]) % 360.0
    out["flags"] = int(out["flags"]) ^ 1
    return out


def _token_occurrences(
    layers: list[Layer],
) -> dict[tuple, list[tuple[Layer, Layer, bool]]]:
    out: dict[tuple, list[tuple[Layer, Layer, bool]]] = defaultdict(list)
    for mirrored, variant in (
        (False, layers),
        (True, [_mirror_layer(layer) for layer in layers]),
    ):
        for i, anchor in enumerate(variant):
            neighbours = sorted(
                (
                    (math.hypot(anchor["x"] - other["x"], anchor["y"] - other["y"]), j)
                    for j, other in enumerate(variant)
                    if j != i
                ),
            )[:PAIR_FANOUT]
            for _distance, j in neighbours:
                out[_pair_token(anchor, variant[j])].append(
                    (anchor, variant[j], mirrored)
                )
    return out


def pair_token_set(layers: list[Layer]) -> set[tuple]:
    return set(_token_occurrences(layers))


def _transform_layers(
    layers: list[Layer],
    *,
    mirrored: bool,
    theta: float,
    scale: float,
    tx: float,
    ty: float,
) -> list[Layer]:
    source = [_mirror_layer(layer) for layer in layers] if mirrored else layers
    if not source:
        return []
    cx = sum(layer["x"] for layer in source) / len(source)
    cy = sum(layer["y"] for layer in source) / len(source)
    cos_t, sin_t = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    out = []
    for layer in source:
        x = (layer["x"] - cx) * scale
        y = (layer["y"] - cy) * scale
        item = dict(layer)
        item["x"] = tx + cx + x * cos_t - y * sin_t
        item["y"] = ty + cy + x * sin_t + y * cos_t
        item["yaw"] = (item["yaw"] + theta) % 360.0
        item["scale"] = max(item["scale"] * scale, 1e-4)
        out.append(item)
    return out


def _transformed_similarity(
    a_layers: list[Layer], b_layers: list[Layer], shared: set[tuple]
) -> float:
    best = matched_similarity(a_layers, b_layers)
    if len(shared) < PAIR_MIN_SHARED:
        return best
    a_occ = _token_occurrences(a_layers)
    b_occ = _token_occurrences(b_layers)
    transform = _pair_transform(a_layers, b_layers, a_occ, b_occ, shared)
    if transform is None:
        return best
    a_mirror, b_mirror, theta, scale, tx, ty, _count = transform
    a_use = [_mirror_layer(layer) for layer in a_layers] if a_mirror else a_layers
    aligned = _transform_layers(
        b_layers, mirrored=b_mirror, theta=theta, scale=scale, tx=tx, ty=ty
    )
    return max(best, matched_similarity(a_use, aligned))


def _pair_transform(
    a_layers: list[Layer],
    b_layers: list[Layer],
    a_occ: dict,
    b_occ: dict,
    shared: set[tuple],
) -> tuple[bool, bool, float, float, float, float, int] | None:
    """Vote on a global transform from token correspondences.

    Each correspondence gives a rotation and scale ratio directly.  Translation
    is derived after rotating B about its own centroid, so every matched anchor
    votes on the same absolute offset.
    """
    b_variants = {
        False: b_layers,
        True: [_mirror_layer(layer) for layer in b_layers],
    }
    centroids = {}
    for mirrored, variant in b_variants.items():
        if variant:
            centroids[mirrored] = (
                sum(layer["x"] for layer in variant) / len(variant),
                sum(layer["y"] for layer in variant) / len(variant),
            )
    votes: dict[tuple, int] = defaultdict(int)
    details: dict[tuple, tuple[bool, bool, float, float, float, float]] = {}
    for token in shared:
        for a_anchor, _a_partner, a_mirror in a_occ.get(token, ())[:4]:
            for b_anchor, _b_partner, b_mirror in b_occ.get(token, ())[:4]:
                theta = (a_anchor["yaw"] - b_anchor["yaw"]) % 360.0
                scale = max(a_anchor["scale"], 1e-4) / max(b_anchor["scale"], 1e-4)
                cx, cy = centroids[b_mirror]
                dx = (b_anchor["x"] - cx) * scale
                dy = (b_anchor["y"] - cy) * scale
                cos_t, sin_t = (
                    math.cos(math.radians(theta)),
                    math.sin(math.radians(theta)),
                )
                tx = a_anchor["x"] - (cx + dx * cos_t - dy * sin_t)
                ty = a_anchor["y"] - (cy + dx * sin_t + dy * cos_t)
                key = (
                    a_mirror,
                    b_mirror,
                    round(theta / PAIR_ANG) % 36,
                    round(math.log(scale) / PAIR_SCALE),
                    round(tx / PAIR_POS),
                    round(ty / PAIR_POS),
                )
                votes[key] += 1
                details[key] = (a_mirror, b_mirror, theta, scale, tx, ty)
    if not votes:
        return None
    key, count = max(votes.items(), key=lambda item: item[1])
    a_mirror, b_mirror, theta, scale, tx, ty = details[key]
    return a_mirror, b_mirror, theta, scale, tx, ty, count


def greedy_dice(
    a_layers: list[Layer], b_layers: list[Layer], gate: float = 0.05
) -> float:
    """Unique-assignment greedy Dice — the cheap score used for pruning."""
    a_layers = [layer for layer in a_layers if layer.get("alpha", 255.0) > 0.0]
    b_layers = [layer for layer in b_layers if layer.get("alpha", 255.0) > 0.0]
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
    a_layers = [layer for layer in a_layers if layer.get("alpha", 255.0) > 0.0]
    b_layers = [layer for layer in b_layers if layer.get("alpha", 255.0) > 0.0]
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
        weights[i][j]
        for i, j in assignment
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
    changed: set[int] | None = None,
) -> list[tuple[str, int, int, float, str, str]]:
    """Score candidate pairs for a vehicle.

    ``changed`` limits scoring to pairs involving those workshop ids.  The
    candidate index still covers every item, but unchanged/unchanged pairs are
    left untouched for the incremental build.
    """
    layers, meta = load_vehicle_layers(conn, vehicle_key)
    ids = [wid for wid in sorted(layers) if len(layers[wid]) >= min_layers]
    if len(ids) < 2:
        return []
    targets = ids if changed is None else [wid for wid in ids if wid in changed]
    if not targets:
        return []

    tokens = {
        wid: pair_token_set(layers[wid])
        or {fingerprint(layer) for layer in layers[wid]}
        for wid in ids
    }
    index: dict[tuple, list[int]] = defaultdict(list)
    for wid in ids:
        for value in tokens[wid]:
            index[value].append(wid)
    rare_index = {
        value: members
        for value, members in index.items()
        if RARE_TOKEN_MIN <= len(members) <= RARE_TOKEN_MAX
    }

    seen: set[tuple[int, int]] = set()
    rows: list[tuple[str, int, int, float, str, str]] = []
    for wid in targets:
        candidates: dict[int, int] = defaultdict(int)
        for value in tokens[wid]:
            members = rare_index.get(value)
            if not members:
                continue
            for other in members:
                if other != wid:
                    candidates[other] += 1
        for other in candidates:
            left, right = (wid, other) if wid < other else (other, wid)
            if (left, right) in seen:
                continue
            seen.add((left, right))
            shared = tokens[left] & tokens[right]
            rare_shared = sum(
                1
                for token in shared
                if RARE_TOKEN_MIN <= len(index.get(token, ())) <= RARE_TOKEN_MAX
            )
            if min(len(tokens[left]), len(tokens[right])) < PAIR_MIN_SHARED:
                min_shared = 1
            else:
                min_shared = max(
                    PAIR_MIN_SHARED,
                    int(0.05 * min(len(tokens[left]), len(tokens[right]))),
                )
            if rare_shared < min_shared:
                continue
            if greedy_dice(layers[left], layers[right]) < CANDIDATE_MIN:
                continue
            score = _transformed_similarity(layers[left], layers[right], shared)
            if score < min_sim:
                continue
            rows.append(
                (
                    vehicle_key,
                    left,
                    right,
                    round(score, 4),
                    meta[left][1],
                    meta[right][1],
                )
            )
    return rows


def _public_items(
    conn: sqlite3.Connection, vehicle_key: str
) -> dict[int, tuple[str, int]]:
    """Return public workshop items as ``{id: (content_hash, layer_count)}``."""
    return {
        int(wid): (str(content_hash or ""), int(layer_count or 0))
        for wid, content_hash, layer_count in conn.execute(
            "SELECT id, json_sha256, decal_layers FROM workshop "
            f"WHERE vehicle_key = ? AND {PUBLIC_WHERE}",
            (vehicle_key,),
        )
    }


def _indexed_items(conn: sqlite3.Connection, vehicle_key: str) -> dict[int, str]:
    return {
        int(wid): str(content_hash or "")
        for wid, content_hash in conn.execute(
            "SELECT workshop_id, content_hash FROM similar_item WHERE vehicle_key = ?",
            (vehicle_key,),
        )
    }


def _scan_plan(
    source_db: str,
    vehicle_key: str,
    changed: list[int],
    min_sim: float,
    min_layers: int,
) -> tuple[str, list[tuple[str, int, int, float, str, str]]]:
    """Worker entry point: score only pairs touching ``changed``."""
    conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=10.0)
    try:
        rows = scan_vehicle(
            conn,
            vehicle_key,
            min_sim=min_sim,
            min_layers=min_layers,
            changed=set(changed),
        )
    finally:
        conn.close()
    return vehicle_key, rows


def _chunks(values: list[int], size: int = 400) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _delete_vehicle_pairs(
    conn: sqlite3.Connection, vehicle_key: str, victims: list[int] | None
) -> None:
    if victims is None:
        conn.execute("DELETE FROM similar_pair WHERE vehicle_key = ?", (vehicle_key,))
        return
    for chunk in _chunks(victims):
        marks = ",".join("?" for _ in chunk)
        conn.execute(
            f"DELETE FROM similar_pair WHERE vehicle_key = ? "
            f"AND (a IN ({marks}) OR b IN ({marks}))",
            [vehicle_key, *chunk, *chunk],
        )


def build(
    source_db: Path,
    site_db: Path,
    *,
    vehicles: Iterable[str] | None = None,
    min_sim: float = DEFAULT_MIN_SIM,
    min_layers: int = DEFAULT_MIN_LAYERS,
    workers: int = 1,
    full: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Build or incrementally update the similarity index in ``site_db``.

    Unchanged vehicles are skipped entirely.  In a changed vehicle only pairs
    touching a new/edited/removed item are rescored; pairs between unchanged
    items are preserved.  ``full=True`` forces a clean rebuild.
    """
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

    last_run = out.execute(
        "SELECT min_sim, min_layers FROM similar_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    params_changed = bool(
        last_run
        and (
            abs(float(last_run[0]) - float(min_sim)) > 1e-9
            or int(last_run[1]) != int(min_layers)
        )
    )
    has_state = out.execute("SELECT 1 FROM similar_item LIMIT 1").fetchone() is not None
    stored_version = out.execute(
        "SELECT value FROM similar_meta WHERE key = 'version'"
    ).fetchone()
    version_changed = not stored_version or stored_version[0] != str(INDEX_VERSION)
    full_run = bool(full or params_changed or version_changed or not has_state)

    plans: list[dict] = []
    for vehicle in targets:
        public = _public_items(source, vehicle)
        indexed = _indexed_items(out, vehicle)
        if full_run:
            changed = set(public)
            stale = set(indexed)
        else:
            changed = {
                wid
                for wid, (content_hash, _layers) in public.items()
                if indexed.get(wid) != content_hash
            }
            stale = set(indexed) - set(public)
        plans.append(
            {
                "vehicle": vehicle,
                "public": public,
                "changed": changed,
                "stale": stale,
                "full": full_run,
            }
        )

    pending = [plan for plan in plans if plan["changed"] or plan["stale"]]
    say(
        f"{len(targets)} vehicles, {len(pending)} changed, "
        f"{sum(len(p['changed']) for p in plans)} new/edited items"
    )

    results: dict[str, list[tuple[str, int, int, float, str, str]]] = {}
    runnable = [plan for plan in pending if plan["changed"]]
    workers = max(1, int(workers or 1))
    if workers > 1 and len(runnable) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(runnable))) as pool:
            futures = {
                pool.submit(
                    _scan_plan,
                    str(source_db),
                    plan["vehicle"],
                    sorted(plan["changed"]),
                    min_sim,
                    min_layers,
                ): plan
                for plan in runnable
            }
            for future in as_completed(futures):
                vehicle, rows = future.result()
                results[vehicle] = rows
                say(f"[{len(results)}/{len(runnable)}] {vehicle}: {len(rows)} pairs")
    else:
        for position, plan in enumerate(runnable, 1):
            _vehicle, rows = _scan_plan(
                str(source_db),
                plan["vehicle"],
                sorted(plan["changed"]),
                min_sim,
                min_layers,
            )
            results[plan["vehicle"]] = rows
            say(f"[{position}/{len(runnable)}] {plan['vehicle']}: {len(rows)} pairs")

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for plan in pending:
        vehicle = plan["vehicle"]
        victims = None if plan["full"] else sorted(plan["changed"] | plan["stale"])
        _delete_vehicle_pairs(out, vehicle, victims)
        rows = results.get(vehicle, [])
        out.executemany(
            "INSERT OR REPLACE INTO similar_pair "
            "(vehicle_key, a, b, sim, created_a, created_b) VALUES (?,?,?,?,?,?)",
            rows,
        )
        if plan["full"]:
            out.execute("DELETE FROM similar_item WHERE vehicle_key = ?", (vehicle,))
            indexed_now = plan["public"]
        else:
            stale = sorted(plan["stale"])
            for chunk in _chunks(stale):
                marks = ",".join("?" for _ in chunk)
                out.execute(
                    f"DELETE FROM similar_item WHERE vehicle_key = ? "
                    f"AND workshop_id IN ({marks})",
                    [vehicle, *chunk],
                )
            indexed_now = {
                wid: plan["public"][wid]
                for wid in plan["changed"]
                if wid in plan["public"]
            }
        out.executemany(
            "INSERT OR REPLACE INTO similar_item "
            "(workshop_id, vehicle_key, content_hash, layer_count, indexed_at) "
            "VALUES (?,?,?,?,?)",
            [
                (wid, vehicle, content_hash, layer_count, now)
                for wid, (content_hash, layer_count) in indexed_now.items()
            ],
        )
        out.commit()

    if full_run and vehicles is None:
        if targets:
            marks = ",".join("?" for _ in targets)
            out.execute(
                f"DELETE FROM similar_pair WHERE vehicle_key NOT IN ({marks})",
                targets,
            )
            out.execute(
                f"DELETE FROM similar_item WHERE vehicle_key NOT IN ({marks})",
                targets,
            )
        else:
            out.execute("DELETE FROM similar_pair")
            out.execute("DELETE FROM similar_item")

    if targets:
        marks = ",".join("?" for _ in targets)
        total_pairs = int(
            out.execute(
                f"SELECT COUNT(*) FROM similar_pair WHERE vehicle_key IN ({marks})",
                targets,
            ).fetchone()[0]
        )
    else:
        total_pairs = 0
    out.execute(
        "INSERT INTO similar_runs "
        "(finished_at, vehicles, models, pairs, min_sim, min_layers) "
        "VALUES (?,?,?,?,?,?)",
        (now, len(targets), len(pending), total_pairs, min_sim, min_layers),
    )
    out.execute(
        "INSERT OR REPLACE INTO similar_meta (key, value) VALUES ('version', ?)",
        (str(INDEX_VERSION),),
    )
    out.commit()
    out.close()
    source.close()
    return {
        "vehicles": len(targets),
        "models": len(pending),
        "pairs": total_pairs,
        "changed": sum(len(p["changed"]) for p in plans),
        "stale": sum(len(p["stale"]) for p in plans),
    }


def main(argv: list[str] | None = None) -> int:
    from .config import WorkshopSettings

    parser = argparse.ArgumentParser(
        description="Build the workshop decal-similarity index"
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="workshop.db (read-only); defaults to AMC_WORKSHOP_DB",
    )
    parser.add_argument(
        "--site",
        type=Path,
        help="site database to write; defaults to AMC_WORKSHOP_SITE_DB",
    )
    parser.add_argument(
        "--vehicle", action="append", help="limit to a vehicle key (repeatable)"
    )
    parser.add_argument("--min-sim", type=float, default=DEFAULT_MIN_SIM)
    parser.add_argument("--min-layers", type=int, default=DEFAULT_MIN_LAYERS)
    parser.add_argument(
        "--workers",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help="parallel vehicle scans (default: up to 4)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="force a clean rebuild instead of the incremental update",
    )
    args = parser.parse_args(argv)
    source = args.source
    site = args.site
    if source is None or site is None:
        settings = WorkshopSettings.from_env()
        source = source or settings.source_db
        site = site or settings.site_db
    result = build(
        source,
        site,
        vehicles=args.vehicle,
        min_sim=args.min_sim,
        min_layers=args.min_layers,
        workers=args.workers,
        full=args.full,
        progress=lambda message: print(message, flush=True),
    )
    print(
        f"indexed {result['pairs']} pairs across {result['vehicles']} vehicles "
        f"({result['changed']} changed, {result['stale']} removed)"
    )
    return 0


def cli() -> None:
    """Console entry point (``amc_workshop_similarity``)."""
    raise SystemExit(main())


if __name__ == "__main__":
    sys.exit(main())
