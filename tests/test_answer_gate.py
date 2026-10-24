import array
import math
import random
import unittest

from landline_hub.line.answer_gate import AnswerGate, RATE


def tone(sec, amp=1500):
    n = int(sec * RATE)
    return array.array("h", (int(amp * (math.sin(2 * math.pi * 440 * i / RATE) + math.sin(2 * math.pi * 480 * i / RATE)) / 2)
                             for i in range(n))).tobytes()


def silence(sec):
    return b"\0\0" * int(sec * RATE)


def voice(sec, amp=2500, seed=1):
    """Not a tone: noise shaped a little, like speech on a phone line."""
    r = random.Random(seed)
    n = int(sec * RATE)
    return array.array("h", (int(amp * r.uniform(-1, 1)) for _ in range(n))).tobytes()


def ringback(on, off, rings, lead=1.0):
    pcm = silence(lead)
    for _ in range(rings):
        pcm += tone(on) + silence(off)
    return pcm


def run(pcm):
    """Feed in 20 ms chunks; return (second it opened, reason) or (None, '')."""
    g = AnswerGate()
    step = RATE // 50 * 2
    for i in range(0, len(pcm), step):
        if g.feed(pcm[i:i + step], i / 2 / RATE) is not None:
            return i / 2 / RATE, g.reason
    return None, ""


class Cadences(unittest.TestCase):
    def test_ringing_alone_never_opens(self):
        for on, off in ((1.0, 3.0), (1.1, 1.9), (1.0, 2.0)):
            with self.subTest(on=on, off=off):
                at, why = run(ringback(on, off, 6)[: -int(off * RATE * 2)])
                self.assertIsNone(at, f"opened at {at} ({why}) during {on}/{off} ringback")

    def test_pickup_after_ringing_opens_quickly(self):
        for on, off in ((1.0, 3.0), (1.1, 1.9)):
            with self.subTest(on=on, off=off):
                head = ringback(on, off, 3)[: -int(off * RATE * 2)] + silence(0.6)
                at, why = run(head + voice(2.0))
                ring_done = len(head) / 2 / RATE
                self.assertIsNotNone(at)
                self.assertLess(at - ring_done, 0.6, why)

    def test_silent_pickup_opens_when_the_next_ring_does_not_come(self):
        head = ringback(1.1, 1.9, 3)[: -int(1.9 * RATE * 2)]
        at, why = run(head + silence(5))
        self.assertEqual(why, "ringback_stopped")
        self.assertLess(at - len(head) / 2 / RATE, 2.6)

    def test_a_ring_out_of_rhythm_is_a_person(self):
        head = ringback(1.1, 1.9, 2)[: -int(1.9 * RATE * 2)]
        at, why = run(head + silence(1.0) + tone(1.0))   # comes 0.9 s early
        self.assertEqual(why, "callee_voice")



def run_full(pcm):
    """Feed everything; return the list of (second, 'open'|'recall', reason)."""
    g = AnswerGate()
    step = RATE // 50 * 2
    out, was_open, n = [], False, 0
    for i in range(0, len(pcm), step):
        g.feed(pcm[i:i + step], i / 2 / RATE)
        if g.recalled > n:
            n = g.recalled
            out.append((i / 2 / RATE, "recall", ""))
        if g.open and not was_open:
            out.append((i / 2 / RATE, "open", g.reason))
        was_open = g.open
    return out


class Recall(unittest.TestCase):
    """10-24: an inferred opening is checked for a few seconds; a ring coming back closes the gate."""

    def test_slow_ring_after_inferred_open_is_recalled_then_real_pickup_opens(self):
        # gaps of 3.8 s are longer than RING_GAP_MAX: the gate opens too early, then the ring comes back
        head = ringback(1.0, 3.8, 3)[: -int(3.8 * RATE * 2)]
        pcm = head + silence(1.0) + voice(2.0)
        ev = run_full(pcm)
        kinds = [k for _, k, _ in ev]
        self.assertIn("recall", kinds, ev)
        self.assertEqual(kinds[-1], "open", ev)

    def test_real_silent_pickup_is_not_recalled(self):
        head = ringback(1.1, 1.9, 3)[: -int(1.9 * RATE * 2)]
        ev = run_full(head + silence(9.0))
        self.assertEqual([k for _, k, _ in ev], ["open"], ev)

    def test_talking_after_open_is_not_recalled(self):
        head = ringback(1.0, 3.0, 2)[: -int(3.0 * RATE * 2)]
        ev = run_full(head + silence(3.6) + voice(1.0, seed=2) + silence(0.5) + voice(1.2, seed=3) + silence(3))
        self.assertNotIn("recall", [k for _, k, _ in ev], ev)

if __name__ == "__main__":
    unittest.main()
