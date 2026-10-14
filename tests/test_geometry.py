import math
import random
import unittest

from fan_tracker.geometry import CalSample, FanPose, aim_at, bearing_deg, fit_pose, wrap_deg


def sample_for(pose: FanPose, pan: float, dist: float, noise_deg: float = 0.0,
               rng: random.Random | None = None) -> CalSample:
    """Where a person stands when they are in the airflow at `pan`."""
    b = pose.heading_deg + pose.mirror * pan + (rng.gauss(0, noise_deg) if rng else 0.0)
    return CalSample(pan, pose.x + dist * math.sin(math.radians(b)),
                     pose.y + dist * math.cos(math.radians(b)))


class AimTest(unittest.TestCase):
    def test_straight_ahead_is_zero_pan(self):
        pose = FanPose(100, 50, heading_deg=0)
        self.assertAlmostEqual(aim_at(pose, 100, 400, target_height_m=0.9).pan, 0.0)

    def test_mirror_flips_pan(self):
        a = aim_at(FanPose(0, 0, 0, 1), 100, 100, target_height_m=1).pan
        b = aim_at(FanPose(0, 0, 0, -1), 100, 100, target_height_m=1).pan
        self.assertAlmostEqual(a, 45.0)
        self.assertAlmostEqual(b, -45.0)

    def test_heading_wraps(self):
        # Fan pointing back toward the sensor (bearing 180), target slightly to +x.
        pose = FanPose(0, 500, heading_deg=180)
        pan = aim_at(pose, 50, 0, target_height_m=1).pan
        self.assertAlmostEqual(pan, wrap_deg(bearing_deg(50, -500) - 180))
        self.assertLess(abs(pan), 10)

    def test_tilt_up_for_close_tall_target(self):
        pose = FanPose(0, 0, 0, height_m=0.5)
        near = aim_at(pose, 0, 114, target_height_m=1.5)   # ~1 m away
        far = aim_at(pose, 0, 457, target_height_m=1.5)    # ~4 m away
        self.assertAlmostEqual(near.tilt, 45.0, delta=0.5)
        self.assertGreater(near.tilt, far.tilt)


class FitTest(unittest.TestCase):
    def check(self, truth: FanPose, samples, **kw):
        r = fit_pose(samples, **kw)
        self.assertEqual(r.pose.mirror, truth.mirror)
        self.assertAlmostEqual(wrap_deg(r.pose.heading_deg - truth.heading_deg), 0, delta=3)
        # The fitted pose should aim within a few degrees at people 2-4 m away,
        # anywhere across the fan's pan range.
        points = [(truth.x + d * math.sin(math.radians(b)), truth.y + d * math.cos(math.radians(b)))
                  for d in (230, 460)
                  for b in (truth.heading_deg + truth.mirror * p for p in (-70, -30, 0, 30, 70))]
        for tx, ty in points:
            want = aim_at(truth, tx, ty, target_height_m=1).pan
            got = aim_at(r.pose, tx, ty, target_height_m=1).pan
            self.assertAlmostEqual(got, want, delta=4, msg=f"at {(tx, ty)}")
        return r

    def test_exact_samples_no_prior(self):
        truth = FanPose(-200, 80, heading_deg=35, mirror=-1)
        samples = [sample_for(truth, p, d) for p, d in [(-40, 250), (0, 350), (40, 200), (20, 450)]]
        r = self.check(truth, samples)
        self.assertLess(r.rms_deg, 0.5)

    def test_noisy_samples_with_fan_prior(self):
        rng = random.Random(3)
        truth = FanPose(250, 120, heading_deg=-50, mirror=1)
        samples = [sample_for(truth, p, d, noise_deg=4, rng=rng)
                   for p, d in [(-45, 300), (0, 250), (45, 280)]]
        measured_fan = (truth.x + 25, truth.y - 20)   # standing next to the fan
        self.check(truth, samples, fan_xy=measured_fan)

    def test_too_few_samples(self):
        with self.assertRaises(ValueError):
            fit_pose([CalSample(0, 0, 100), CalSample(30, 50, 100)])


if __name__ == "__main__":
    unittest.main()
