"""Replay recorded line audio through the answer gate.

  python tools/gate_replay.py rec.wav [rec2.wav ...]     # print what the gate decides
  python tools/gate_replay.py --exam folder/              # grade every labelled recording

A recording comes from the hub with [answer_detection].keep_audio on (data_dir/gate_audio):
an 8 kHz mono wav plus a json whose "label.answered_at" you fill in after listening
(seconds from the start of the wav when the callee really picked up; null = nobody did;
"?" = not labelled yet, skipped by the exam).

Exam rules: the gate must never stay open before answered_at (opening early is fine only
if it is taken back before the callee picks up), and must be open within OPEN_WITHIN
seconds after it; with answered_at null it must not be open at the end.
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from landline_hub.line.answer_gate import RATE, AnswerGate  # noqa: E402

OPEN_WITHIN = 3.5     # a silent pick-up is only noticed when the next ring fails to come


def replay(wav_path: Path) -> tuple[list[tuple[float, str, str]], float]:
    with wave.open(str(wav_path), "rb") as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{wav_path}: needs 8 kHz mono 16-bit")
        pcm = w.readframes(w.getnframes())
    g, out = AnswerGate(), []
    step, was_open, recalled = RATE // 50 * 2, False, 0
    for i in range(0, len(pcm), step):
        t = i / 2 / RATE
        g.feed(pcm[i:i + step], t)
        if g.recalled > recalled:
            recalled = g.recalled
            out.append((t, "recall", ""))
        if g.open and not was_open:
            out.append((t, "open", g.reason))
        was_open = g.open
    return out, len(pcm) / 2 / RATE


def grade(events, length: float, answered_at: float | None) -> str | None:
    """None = pass, else what went wrong."""
    spans, opened = [], None                      # (open, close) intervals of the gate
    for t, kind, _ in events:
        if kind == "open":
            opened = t
        elif kind == "recall" and opened is not None:
            spans.append((opened, t))
            opened = None
    if opened is not None:
        spans.append((opened, length))
    if answered_at is None:
        return f"open at the end (since {spans[-1][0]:.1f}s) but nobody answered" if opened is not None else None
    live = [(a, b) for a, b in spans if b > answered_at]   # spans still open at/after the pick-up
    if not live:
        return f"never open after the pick-up at {answered_at:.1f}s"
    a = live[0][0]
    if a < answered_at - 0.5:
        return f"opened at {a:.1f}s while still ringing and stayed open (pick-up {answered_at:.1f}s)"
    if a > answered_at + OPEN_WITHIN:
        return f"opened {a - answered_at:.1f}s after the pick-up (limit {OPEN_WITHIN}s)"
    return None


def main(argv):
    if argv[:1] == ["--exam"]:
        folder = Path(argv[1])
        bad = total = 0
        for js in sorted(folder.glob("*.json")):
            label = json.loads(js.read_text(encoding="utf-8")).get("label") or {}
            if label.get("answered_at") == "?":
                continue                                   # not labelled yet
            wav = js.with_suffix(".wav")
            if not wav.exists():
                continue
            ev, length = replay(wav)
            err = grade(ev, length, label["answered_at"])
            total += 1
            bad += err is not None
            print(("FAIL " if err else "ok   ") + wav.name, err or "", label.get("note", ""))
        print(f"{total - bad}/{total} passed")
        return 1 if bad else 0
    for p in argv:
        ev, length = replay(Path(p))
        print(p, f"({length:.1f}s)")
        for t, kind, why in ev:
            print(f"  {t:6.2f}s {kind} {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
