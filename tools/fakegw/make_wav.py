"""Make the audio the fake gateway plays into every call.

  python make_wav.py tone            a 1 s beep every 2 s (generic "someone talking")
  python make_wav.py keys 101        2 s silence, then DTMF 101 (dials an extension)
"""
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from landline_hub.line.dtmf import tones  # noqa: E402

RATE = 8000


def silence(sec):
    return b"\0\0" * int(RATE * sec)


def beep(sec, f=440, amp=6000):
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * f * i / RATE))) for i in range(int(RATE * sec)))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "tone"
    if mode == "keys":
        pcm = silence(2) + tones(sys.argv[2], RATE) + silence(30)
    else:
        pcm = (beep(1) + silence(1)) * 15
    out = Path(__file__).parent / "play.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
    print(out)


if __name__ == "__main__":
    main()
