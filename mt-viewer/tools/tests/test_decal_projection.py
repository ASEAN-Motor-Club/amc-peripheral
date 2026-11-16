import math
import random
import unittest

from tools.decal_projection import mirror_uv, primary_uv, rotation_axis


def mat_vec(rows, v):
    return [sum(a*b for a, b in zip(row, v)) for row in rows]


def assembly_primary(p, position, yaw, pitch, roll, scale, stretch, flip):
    """Independent transcription of 5020.asm instructions 35-57."""
    q = rotation_axis(yaw, pitch)
    qw = -sum(x*x for x in q)
    q2x = 0.0
    r0w = 2.0 * sum(a*b for a, b in zip(q, p))
    r5 = [p[0]*qw, p[1]*qw, p[2]*q[1], p[0]*q[2]]
    r3zw = [q[0]*r0w + r5[0], q[1]*r0w + r5[1]]
    cross_terms = [-q[2]*p[1] + r5[2], -q[0]*p[2] + r5[3]]
    r3zw = [a + b*q2x for a, b in zip(r3zw, cross_terms)]
    t = 2*math.pi*(-yaw-0.25)
    r5x = math.cos(t)*r3zw[0] - math.sin(t)*r3zw[1]
    r5y = math.sin(t)*r3zw[0] + math.cos(t)*r3zw[1]
    shifted = [r5x-position[0], r5y+position[1]]
    b = 2*math.pi*roll
    rolled = [math.cos(b)*shifted[0]-math.sin(b)*shifted[1],
              math.sin(b)*shifted[0]+math.cos(b)*shifted[1]]
    d = [255*scale*stretch, 255*scale*(1-2*flip)]
    return [(x-0.5)/den+0.5 for x, den in zip(rolled, d)]


class DecalProjectionTests(unittest.TestCase):
    def test_zero_angles_match_expanded_shader(self):
        got = primary_uv((100, 200, 300), (0, 0), 0, 0, 0, 1)
        # At zero turns the pitch expression is 2π*(0+0.25)/2 = π/4,
        # so R(p) = (300,-200,100), not a Z-only quarter turn.
        expected = [(-200.5)/255+0.5, (-300.5)/255+0.5]
        for a, b in zip(got, expected):
            self.assertAlmostEqual(a, b, places=12)

    def test_simplified_projection_matches_assembly(self):
        rng = random.Random(5020)
        for _ in range(50):
            args = (
                [rng.uniform(-1000, 1000) for _ in range(3)],
                [rng.uniform(-1000, 1000) for _ in range(2)],
                rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1),
                rng.uniform(0.01, 5), rng.uniform(0.1, 4), rng.choice([0, 1]),
            )
            got = primary_uv(*args)
            expected = assembly_primary(*args)
            for a, b in zip(got, expected):
                self.assertAlmostEqual(a, b, places=10)

    def test_mirror_uses_workshop_yaw_negative_roll_and_positive_one_unit_shift(self):
        p = (120, -240, 360)
        pos = (20, 30)
        yaw, pitch, roll, scale = 0.17, -0.11, 0.08, 1.3
        got = mirror_uv(p, pos, yaw, pitch, roll, scale, 1.7, 0)
        # MrBug 24982 in-game A/B: mirror uses the payload's primary yaw.
        # Keep the assembly-derived X translation and negative roll/stretch.
        expected = assembly_primary(
            p, (-pos[0]-1, pos[1]), yaw, pitch, -roll, scale, -1.7, 0,
        )
        for a, b in zip(got, expected):
            self.assertAlmostEqual(a, b, places=12)


if __name__ == '__main__':
    unittest.main()
