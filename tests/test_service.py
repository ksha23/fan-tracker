import hashlib
import json
import unittest

from fan_tracker.aqara import AqaraClient
from fan_tracker.config import Config
from fan_tracker.service import Service


class FakeAqara:
    def __init__(self):
        self.ts, self.value, self.writes = 1, "[]", []

    def query(self, did, rids):
        return [{"resourceId": rids[0], "value": self.value, "timeStamp": self.ts}]

    def write(self, did, values):
        self.writes.append(values)


class FakeHA:
    def __init__(self):
        self.states = {"input_boolean.fan_tracking": "on", "fan.dreo": "on"}
        self.changed = {}
        self.numbers, self.published, self.calls = [], {}, []

    def state(self, eid):
        if eid not in self.states:
            return None
        st = {"state": self.states[eid]}
        if eid in self.changed:
            st["last_changed"] = self.changed[eid]
        return st

    def set_number(self, eid, v):
        self.numbers.append((eid, v))

    def service(self, domain, svc, **data):
        self.calls.append((domain, svc, data.get("entity_id")))

    def publish(self, eid, state, attrs):
        self.published[eid] = (state, attrs)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(fan_entity="fan.dreo", pan_entity="number.pan",
                          tilt_entity="number.tilt", fan_y=-50, min_command_interval_s=0)
        self.aq, self.ha = FakeAqara(), FakeHA()
        self.svc = Service(self.cfg, aqara=self.aq, ha=self.ha)

    def feed(self, now, targets):
        self.aq.ts += 1
        self.aq.value = json.dumps([{"id": i, "x": x, "y": y, "state": "1"}
                                    for i, (x, y) in enumerate(targets)])
        self.svc.step(now)

    def test_tracks_and_publishes(self):
        self.feed(10.0, [(0, 300)])
        self.assertEqual(self.aq.writes, [{"4.22.85": 1}])
        self.assertEqual(self.ha.numbers[0], ("number.pan", 0))
        self.assertEqual(self.ha.published["sensor.fan_tracker"][0], "tracking")

    def test_enabling_stops_oscillation(self):
        self.feed(10.0, [(0, 300)])
        self.assertIn(("switch", "turn_off", "switch.air_circulator_vertical_oscillation"), self.ha.calls)
        self.assertIn(("switch", "turn_off", "switch.air_circulator_horizontal_oscillation"), self.ha.calls)

    def test_reporting_is_refreshed_every_minute(self):
        self.feed(10.0, [(0, 300)])
        self.feed(40.0, [(0, 300)])
        self.feed(71.0, [(0, 300)])
        self.assertEqual(self.aq.writes, [{"4.22.85": 1}, {"4.22.85": 1}])

    def test_stale_timestamp_is_ignored(self):
        self.feed(10.0, [(0, 300)])
        n = len(self.ha.numbers)
        self.aq.value = json.dumps([{"id": 0, "x": 300, "y": 300, "state": "1"}])
        self.svc.step(11.0)   # same timestamp, new value: not a new reading
        self.assertEqual(len(self.ha.numbers), n)

    def test_does_nothing_when_disabled_or_fan_off(self):
        self.ha.states["input_boolean.fan_tracking"] = "off"
        self.feed(10.0, [(0, 300)])
        self.ha.states["input_boolean.fan_tracking"] = "on"
        self.ha.states["fan.dreo"] = "off"
        self.feed(20.0, [(0, 300)])
        self.assertEqual(self.ha.numbers, [])
        self.assertEqual(self.ha.published["sensor.fan_tracker"][0], "fan off")

    def test_disabling_turns_reporting_off(self):
        self.feed(10.0, [(0, 300)])
        self.ha.states["input_boolean.fan_tracking"] = "off"
        self.svc.step(20.0)
        self.assertEqual(self.aq.writes[-1], {"4.22.85": 0})

    def test_quick_off_on_releases_the_target(self):
        self.ha.changed["input_boolean.fan_tracking"] = "t1"
        self.feed(10.0, [(0, 300)])
        self.assertIsNotNone(self.svc.tracker.target_id)
        self.ha.changed["input_boolean.fan_tracking"] = "t2"  # off and on between two checks
        self.svc._refresh_flags(20.0)
        self.assertIsNone(self.svc.tracker.target_id)

    def test_unchanged_switch_keeps_the_target(self):
        self.ha.changed["input_boolean.fan_tracking"] = "t1"
        self.feed(10.0, [(0, 300)])
        self.svc._refresh_flags(20.0)
        self.assertIsNotNone(self.svc.tracker.target_id)


class SignTest(unittest.TestCase):
    def test_sign_matches_documented_rule(self):
        c = AqaraClient("AppID", "KeyID", "SecretKey")
        h = {"Accesstoken": "Tok", "Appid": "AppID", "Keyid": "KeyID", "Nonce": "N1",
             "Time": "1700000000000"}
        src = "Accesstoken=Tok&Appid=AppID&Keyid=KeyID&Nonce=N1&Time=1700000000000SecretKey"
        self.assertEqual(c.sign(h), hashlib.md5(src.lower().encode()).hexdigest())
        del h["Accesstoken"]
        src = "Appid=AppID&Keyid=KeyID&Nonce=N1&Time=1700000000000SecretKey"
        self.assertEqual(c.sign(h), hashlib.md5(src.lower().encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
