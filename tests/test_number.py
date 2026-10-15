import unittest

from landline_hub.domain.number import Kind, DialNumber, Rejected, TaiwanPolicy, normalize
from landline_hub.domain.permissions import Client, ClientRole, may_dial


class NormalizeTest(unittest.TestCase):
    def test_international_prefix(self):
        self.assertEqual(normalize("+886 2-1234-5678"), "0212345678")
        self.assertEqual(normalize("00886912345678"), "0912345678")

    def test_emergency_spellings_collapse(self):
        for raw in ["110", "110#", "(110)", "+886110", "886-110", "0110", " 1 1 0 "]:
            self.assertEqual(normalize(raw), "110", raw)


class TaiwanPolicyTest(unittest.TestCase):
    p = TaiwanPolicy()

    def test_regular(self):
        self.assertEqual(self.p.parse("02-1234-5678"), DialNumber("0212345678", Kind.REGULAR))
        self.assertEqual(self.p.parse("0912-345-678").kind, Kind.REGULAR)

    def test_premium(self):
        self.assertEqual(self.p.parse("0204-123456").kind, Kind.PREMIUM)

    def test_emergency_every_spelling(self):
        for raw in ["110", "110#", "(110)", "+886110", "119", "112"]:
            self.assertEqual(self.p.parse(raw).kind, Kind.EMERGENCY, raw)

    def test_garbage_rejected(self):
        for raw in ["", "abc", "123", "12345678901234", "1234567"]:
            self.assertIsInstance(self.p.parse(raw), Rejected, raw)


class PermissionTest(unittest.TestCase):
    p = TaiwanPolicy()

    def test_person_can_call_emergency(self):
        self.assertTrue(may_dial(Client("phone", ClientRole.HANDSET), self.p.parse("110")))

    def test_program_cannot_by_default(self):
        agent = Client("ai", ClientRole.AGENT)
        self.assertFalse(may_dial(agent, self.p.parse("+886110")))
        self.assertFalse(may_dial(agent, self.p.parse("0204123456")))
        self.assertTrue(may_dial(agent, self.p.parse("0212345678")))

    def test_operator_can_grant_program(self):
        agent = Client("ai", ClientRole.AGENT, frozenset({Kind.EMERGENCY}))
        self.assertTrue(may_dial(agent, self.p.parse("119")))

    def test_premium_off_for_everyone_by_default(self):
        self.assertFalse(may_dial(Client("phone", ClientRole.HANDSET), self.p.parse("0209123456")))


if __name__ == "__main__":
    unittest.main()
