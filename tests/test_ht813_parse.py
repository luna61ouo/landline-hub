import unittest

from landline_hub.domain.incoming import CallerId, LineReleased, LineSeized, RingStart, RingStop
from landline_hub.gateway.grandstream_ht813.parse import parse


class Ht813ParseTest(unittest.TestCase):
    def test_lines(self):
        cases = {
            "GS_ATA: Nuvoton::decodeDtmfCidNumber, CID Caller Number 0212345678": CallerId("0212345678"),
            "GS_ATA: Dispatching event 36 (LINE_RING_START) on port 1:0": RingStart(),
            "GS_ATA: Dispatching event 37 (LINE_RING_STOP) on port 1:0": RingStop(),
            "GS_ATA: Nuvoton::fxoHookSet, Set Hook to  OffHook on port 1:0": LineSeized(),
            "GS_ATA: Nuvoton::fxoHookSet, Set Hook to  OnHook on port 1:0": LineReleased(),
        }
        for line, want in cases.items():
            self.assertEqual(parse(line), want, line)

    def test_ignores_other_ports_and_noise(self):
        self.assertIsNone(parse("GS_ATA: Dispatching event 36 (LINE_RING_START) on port 0:0"))
        self.assertIsNone(parse("something else entirely"))


if __name__ == "__main__":
    unittest.main()
