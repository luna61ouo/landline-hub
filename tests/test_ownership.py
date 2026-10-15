import unittest

from landline_hub.domain.ownership import Busy, Free, Granted, claim, release


class OwnershipTest(unittest.TestCase):
    def test_second_claim_is_busy(self):
        g = claim(Free(), "phone-a", "outbound", 0)
        self.assertIsInstance(g, Granted)
        b = claim(g.state, "agent", "outbound", 1)
        self.assertIsInstance(b, Busy)
        self.assertEqual(b.held_by.owner, "phone-a")

    def test_only_owner_releases(self):
        s = claim(Free(), "phone-a", "outbound", 0).state
        self.assertIs(release(s, "agent"), s)
        self.assertIsInstance(release(s, "phone-a"), Free)


if __name__ == "__main__":
    unittest.main()
