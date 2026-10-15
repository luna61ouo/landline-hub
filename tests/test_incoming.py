import itertools
import unittest

from landline_hub.domain import incoming as inc


def ids():
    c = itertools.count(1)
    return lambda: f"c{next(c)}"


class IncomingTest(unittest.TestCase):
    def test_missed_call_by_abandon(self):
        new = ids()
        s, ev = inc.step(inc.Idle(), inc.RingStart(), 0, new)
        self.assertEqual(ev[0]["type"], "incoming")
        s, ev = inc.step(s, inc.CallerId("0912345678"), 0.5, new)
        self.assertEqual(ev[0]["type"], "caller_id")
        s, ev = inc.step(s, inc.RingStop(), 1.0, new)
        s, ev = inc.tick(s, 5.0)
        self.assertEqual(ev, [])
        s, ev = inc.tick(s, 8.1)
        self.assertIsInstance(s, inc.Idle)
        self.assertEqual(ev[0]["result"], "missed")

    def test_answered_then_released(self):
        new = ids()
        s, _ = inc.step(inc.Idle(), inc.RingStart(), 0, new)
        s, ev = inc.step(s, inc.LineSeized(), 3, new)
        self.assertEqual(ev[0]["type"], "answered")
        s, ev = inc.step(s, inc.LineReleased(), 43, new)
        self.assertEqual((ev[0]["result"], ev[0]["talk_sec"]), ("answered", 40.0))

    def test_same_caller_id_twice_is_silent(self):
        new = ids()
        s, _ = inc.step(inc.Idle(), inc.CallerId("021"), 0, new)
        s, ev = inc.step(s, inc.CallerId("021"), 1, new)
        self.assertEqual(ev, [])


if __name__ == "__main__":
    unittest.main()
