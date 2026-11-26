import unittest

from payments.durations import parse_duration_ms


class ParseDurationTest(unittest.TestCase):
    def test_milliseconds(self) -> None:
        self.assertEqual(parse_duration_ms("250ms"), 250)

    def test_minutes(self) -> None:
        self.assertEqual(parse_duration_ms("2m"), 120_000)

    def test_rejects_junk(self) -> None:
        with self.assertRaises(ValueError):
            parse_duration_ms("soon")
