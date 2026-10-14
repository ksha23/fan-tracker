import math
import unittest

from fan_tracker.controller import Tracker, TrackerSettings
from fan_tracker.fp2 import Target, parse_targets
from fan_tracker.geometry import FanPose


def tracker(**kw) -> Tracker:
    s = TrackerSettings(smoothing=1.0, **kw)
    return Tracker(FanPose(0, 0, heading_deg=0), s)


class ControllerTest(unittest.TestCase):
    def test_first_reading_commands(self):
        t = tracker()
        cmd = t.update(0.0, [Target("1", 0, 300)])
        self.assertEqual(cmd.pan, 0)

    def test_deadband_suppresses_small_moves(self):
        t = tracker(pan_deadband_deg=6)
        t.update(0.0, [Target("1", 0, 300)])
        self.assertIsNone(t.update(5.0, [Target("1", 15, 300)]))     # ~3 degrees
        self.assertIsNotNone(t.update(10.0, [Target("1", 80, 300)]))  # ~15 degrees

    def test_rate_limit_then_catch_up(self):
        t = tracker(min_command_interval_s=2.0)
        t.update(0.0, [Target("1", 0, 300)])
        self.assertIsNone(t.update(1.0, [Target("1", 300, 300)]))
        cmd = t.update(2.5, [Target("1", 300, 300)])
        self.assertEqual(cmd.pan, 45)

    def test_pan_is_clamped(self):
        t = tracker(pan_limits=(-75, 75))
        self.assertEqual(t.update(0.0, [Target("1", 300, -10)]).pan, 75)

    def test_sticks_to_current_target(self):
        t = tracker()
        t.update(0.0, [Target("a", 0, 300)])
        t.update(3.0, [Target("b", -100, 100), Target("a", 200, 300)])
        self.assertEqual(t.target_id, "a")

    def test_lost_target_resets_after_timeout(self):
        t = tracker(lost_after_s=8)
        t.update(0.0, [Target("a", 0, 300)])
        t.update(5.0, [])
        self.assertEqual(t.target_id, "a")
        t.update(9.0, [])
        self.assertIsNone(t.target_id)
        self.assertIsNone(t.update(10.0, []))

    def test_fixed_tilt_mode(self):
        t = tracker(tilt_mode="fixed", fixed_tilt_deg=15)
        self.assertEqual(t.update(0.0, [Target("1", 0, 100)]).tilt, 15)

    def test_commands_are_whole_steps(self):
        t = tracker(angle_step_deg=5)
        cmd = t.update(0.0, [Target("1", 80, 300)])     # ~14.9 degrees
        self.assertEqual(cmd.pan, 15)
        self.assertEqual(cmd.tilt % 5, 0)

    def test_no_flicker_on_step_boundary(self):
        t = tracker(angle_step_deg=5, pan_deadband_deg=6)
        y = 300
        x_at = lambda deg: y * math.tan(math.radians(deg))
        self.assertEqual(t.update(0.0, [Target("1", x_at(2.4), y)]).pan, 0)
        self.assertIsNone(t.update(5.0, [Target("1", x_at(2.6), y)]))   # would round to 5
        self.assertIsNone(t.update(10.0, [Target("1", x_at(2.4), y)]))
        self.assertEqual(t.update(15.0, [Target("1", x_at(7.0), y)]).pan, 5)


    def test_ignores_target_at_the_fan(self):
        t = Tracker(FanPose(-45, 154, heading_deg=0), TrackerSettings(smoothing=1.0))
        cmd = t.update(0.0, [Target("5", -45, 154), Target("8", -45, 400)])
        self.assertEqual(t.target_id, "8")
        self.assertEqual(cmd.pan, 0)
        self.assertIsNone(Tracker(FanPose(-45, 154, 0)).update(0.0, [Target("5", -40, 150)]))

    def test_still_ghost_loses_to_a_mover(self):
        t = tracker()
        t.update(0.0, [Target("g", 0, 300)])               # only a still ghost so far
        self.assertEqual(t.target_id, "g")
        t.update(1.0, [Target("g", 0, 300), Target("p", 200, 200)])
        self.assertEqual(t.target_id, "g")                  # p has not moved yet
        t.update(2.0, [Target("g", 0, 300), Target("p", 230, 220)])
        self.assertEqual(t.target_id, "p")

    def test_keeps_a_person_who_stops_moving(self):
        t = tracker()
        t.update(0.0, [Target("p", 0, 300)])
        t.update(1.0, [Target("p", 40, 300)])               # p moved once
        t.update(2.0, [Target("p", 40, 300), Target("q", -200, 200)])
        t.update(3.0, [Target("p", 40, 300), Target("q", -150, 230)])  # q moves now
        self.assertEqual(t.target_id, "p")

class ParseTest(unittest.TestCase):
    def test_parses_json_string_and_filters_inactive(self):
        v = ('[{"id":0,"x":"51","y":180,"rangeId":1,"state":"1"},'
             '{"id":1,"x":0,"y":0,"state":"0"},{"id":2,"y":5,"state":"1"}]')
        self.assertEqual(parse_targets(v), [Target("0", 51.0, 180.0)])

    def test_bad_values(self):
        for v in (None, "", "not json", "{}", 5):
            self.assertEqual(parse_targets(v), [])


if __name__ == "__main__":
    unittest.main()
