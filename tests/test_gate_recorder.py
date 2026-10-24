import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

from landline_hub.line.answer_gate import AnswerGate, RATE
from landline_hub.line.gate_recorder import GateRecorder, TAIL_SEC

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_answer_gate import ringback, silence, voice  # noqa: E402
import gate_replay  # noqa: E402


def run_with_recorder(pcm, folder):
    """Drive gate + recorder the way the hub's pump does."""
    rec = GateRecorder(folder, "test1")
    g = AnswerGate(log=lambda t, **f: rec.event(t, **f))
    step = RATE // 50 * 2
    for i in range(0, len(pcm), step):
        raw = pcm[i:i + step]
        if rec.active:
            rec.feed(raw)
            if g.open and g.verify_until is None:
                rec.settled()
        if not g.open or g.verify_until is not None:
            g.feed(raw, i / 2 / RATE)
    return rec, g


class Recorder(unittest.TestCase):
    def test_keeps_ringing_until_settled_plus_tail_and_replays_the_same(self):
        head = ringback(1.1, 1.9, 3)[: -int(1.9 * RATE * 2)] + silence(0.6)
        pcm = head + voice(2.0) + silence(20)
        with tempfile.TemporaryDirectory() as d:
            rec, g = run_with_recorder(pcm, d)
            self.assertTrue(g.open)
            self.assertFalse(rec.active)
            self.assertLess(len(rec.pcm), len(pcm))            # stopped after the tail, not at hang-up
            wav = rec.save("hangup")
            meta = json.loads(wav.with_suffix(".json").read_text())
            self.assertEqual(meta["label"]["answered_at"], "?")
            self.assertIn("gate_open", [e["what"] for e in meta["events"]])
            with wave.open(str(wav)) as w:
                self.assertEqual(w.getframerate(), RATE)
            ev, _ = gate_replay.replay(wav)
            self.assertEqual([k for _, k, _ in ev][-1], "open")

    def test_exam_grades(self):
        ev = [(5.0, "open", "ringback_stopped"), (6.5, "recall", ""), (10.0, "open", "callee_voice")]
        self.assertIsNone(gate_replay.grade(ev, 20, 9.8))          # wrong open taken back in time
        self.assertIsNotNone(gate_replay.grade(ev[:1], 20, 9.8))   # wrong open never taken back
        self.assertIsNotNone(gate_replay.grade(ev, 20, None))      # nobody answered but open at end
        self.assertIsNone(gate_replay.grade([], 50, None))         # rang out, never opened
        self.assertIsNotNone(gate_replay.grade([(16.0, "open", "x")], 20, 10.0))  # too late


if __name__ == "__main__":
    unittest.main()
