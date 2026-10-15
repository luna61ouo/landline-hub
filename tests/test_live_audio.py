import unittest

from landline_hub.service import LIVE_MAX_QUEUE_SEC, Hub, Session


class FakeLine:
    def __init__(self):
        self.buf = bytearray()

    def play(self, pcm):
        self.buf += pcm

    def clear(self):
        self.buf.clear()

    def queued_sec(self):
        return len(self.buf) / 16000


def play(s, pcm, live):
    Hub.play(None, s, pcm, live)


class LiveAudio(unittest.TestCase):
    def test_a_person_talking_before_pickup_is_not_queued(self):
        s = Session("c", "outbound", "0212345678", FakeLine(), "phone")
        for _ in range(500):                       # 10 s of dialling
            play(s, b"\1\0" * 160, live=True)
        self.assertEqual(s.line.queued_sec(), 0)

    def test_a_person_never_lags_behind(self):
        s = Session("c", "outbound", "0212345678", FakeLine(), "phone", state="connected")
        for _ in range(100):                       # the phone sends faster than the line drains
            play(s, b"\1\0" * 160, live=True)
        self.assertLessEqual(s.line.queued_sec(), LIVE_MAX_QUEUE_SEC + 0.02)

    def test_a_voice_model_may_queue_ahead(self):
        s = Session("c", "outbound", "0212345678", FakeLine(), "agent", state="connected")
        for _ in range(100):
            play(s, b"\1\0" * 160, live=False)
        self.assertAlmostEqual(s.line.queued_sec(), 2.0)


if __name__ == "__main__":
    unittest.main()
