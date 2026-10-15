import random
import unittest

from landline_hub.domain.pbx import (
    ACTION_TYPES, Bridge, CallerHungUp, Choosing, Collecting, Connected, Digit, Ended, Farewell,
    HandsetAnswered, Pbx, Play, Prompt, PromptFinished, Ring, RingingExt, StopRinging, Tick, Timers,
    build_directory,
)

DIRECTORY = build_directory(
    [{"ext": "0", "devices": ["front"]},
     {"ext": "101", "devices": ["alex"]},
     {"ext": "102", "devices": ["bo", "cy"]}],
    operator="0")
T = Timers(digit_timeout=8, ring_sec=20, choice_timeout=8, max_retries=2, max_wait_rounds=2)


def run(pbx, inputs):
    """inputs: list of (time, input).  Returns final state and all actions."""
    s, acts = pbx.start(0)
    out = list(acts)
    for now, i in inputs:
        s, a = pbx.step(s, i, now)
        out += a
    return s, out


class DirectoryTest(unittest.TestCase):
    def test_rejects_bad_directories(self):
        bad = [
            ([{"ext": "1", "devices": ["a"]}, {"ext": "10", "devices": ["b"]}], None),   # prefix
            ([{"ext": "1", "devices": ["a"]}, {"ext": "1", "devices": ["b"]}], None),    # duplicate
            ([{"ext": "1a", "devices": ["a"]}], None),                                   # not digits
            ([{"ext": "1", "devices": []}], None),                                       # no phones
            ([{"ext": "1", "devices": ["a"]}], "9"),                                     # operator missing
        ]
        for entries, op in bad:
            with self.assertRaises(ValueError, msg=entries):
                build_directory(entries, op)


class PbxFlowTest(unittest.TestCase):
    pbx = Pbx(DIRECTORY, T)

    def test_dial_extension_and_answer(self):
        s, acts = run(self.pbx, [(1, Digit("1")), (1.5, Digit("0")), (2, Digit("2")),
                                 (5, HandsetAnswered("cy"))])
        self.assertEqual(s, Connected("cy"))
        self.assertIn(Ring(("bo", "cy")), acts)
        self.assertIn(Bridge("cy"), acts)

    def test_wrong_phone_cannot_take_the_call(self):
        s, _ = run(self.pbx, [(1, Digit("1")), (1, Digit("0")), (1, Digit("1")), (2, HandsetAnswered("bo"))])
        self.assertIsInstance(s, RingingExt)

    def test_no_answer_offers_choice_then_keep_waiting(self):
        s, acts = run(self.pbx, [(1, Digit("1")), (1, Digit("0")), (1, Digit("1")), (21.5, Tick())])
        self.assertIsInstance(s, Choosing)
        self.assertIn(Play(Prompt.WAIT_OR_OPERATOR), acts)
        s, a = self.pbx.step(s, Digit("1"), 23)
        self.assertEqual((s.ext, s.rounds), ("101", 2))
        self.assertEqual(a, [Ring(("alex",))])

    def test_choice_zero_goes_to_operator(self):
        s, _ = run(self.pbx, [(1, Digit("1")), (1, Digit("0")), (1, Digit("1")), (21.5, Tick()), (22, Digit("0"))])
        self.assertTrue(s.is_operator)

    def test_waiting_rounds_are_capped(self):
        s, _ = run(self.pbx, [(1, Digit("1")), (1, Digit("0")), (1, Digit("1")), (21.5, Tick()),
                              (22, Digit("1")), (42.5, Tick())])
        self.assertTrue(isinstance(s, RingingExt) and s.is_operator)

    def test_operator_no_answer_says_goodbye_and_hangs_up(self):
        s, acts = run(self.pbx, [(9, Tick()), (30, Tick())])
        self.assertIsInstance(s, Farewell)
        self.assertIn(Play(Prompt.NO_ANSWER), acts)
        s, a = self.pbx.step(s, PromptFinished(), 33)
        self.assertEqual((s, a[-1].__class__.__name__), (Ended(), "Hangup"))

    def test_wrong_extension_retries_then_operator(self):
        s, acts = run(self.pbx, [(1, Digit("9")), (2, Digit("9")), (3, Digit("9"))])
        self.assertEqual(acts.count(Play(Prompt.INVALID)), 2)
        self.assertTrue(isinstance(s, RingingExt) and s.is_operator)

    def test_hash_ends_entry(self):
        s, _ = run(self.pbx, [(1, Digit("1")), (2, Digit("#"))])
        self.assertIsInstance(s, Collecting)
        self.assertEqual(s.retries, 1)

    def test_caller_hangs_up_while_ringing(self):
        s, acts = run(self.pbx, [(1, Digit("0")), (3, CallerHungUp())])
        self.assertEqual((s, acts[-1]), (Ended(), StopRinging()))

    def test_no_operator_configured(self):
        pbx = Pbx(build_directory([{"ext": "7", "devices": ["x"]}], None), T)
        s, acts = run(pbx, [(9, Tick())])
        self.assertIsInstance(s, Farewell)


class TollFraudTest(unittest.TestCase):
    """Whatever a caller presses, the only things that can happen are the five
    harmless actions.  There is no way to reach an outside line."""

    def test_random_key_storms_never_leave_the_action_set(self):
        pbx = Pbx(DIRECTORY, T)
        rng = random.Random(42)
        keys = list("0123456789*#")
        for _ in range(500):
            s, acts = pbx.start(0)
            now = 0.0
            for _ in range(60):
                now += rng.choice([0.1, 0.5, 3, 9, 21])
                i = rng.choice([Digit(rng.choice(keys)), Tick(), Tick(), PromptFinished(),
                                HandsetAnswered(rng.choice(["front", "alex", "bo", "zz"]))])
                s, a = pbx.step(s, i, now)
                acts += a
            for a in acts:
                self.assertIsInstance(a, ACTION_TYPES)
                if isinstance(a, Bridge):
                    self.assertIn(a.device, {"front", "alex", "bo", "cy"})


if __name__ == "__main__":
    unittest.main()
