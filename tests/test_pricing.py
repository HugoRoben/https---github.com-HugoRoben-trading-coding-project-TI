import math
import unittest

from modules.models.black_scholes import black_scholes


class BlackScholesTests(unittest.TestCase):
    def test_classic_call_and_put(self):
        args = (100, 100, 1, 0.05, 0, 0.2)
        self.assertAlmostEqual(black_scholes("call", *args), 10.4505835722, places=9)
        self.assertAlmostEqual(black_scholes("put", *args), 5.5735260223, places=9)

    def test_put_call_parity_with_dividends_and_negative_rate(self):
        args = (110, 103, 1.5, -0.01, 0.025, 0.29)
        call, put = (black_scholes(kind, *args) for kind in ("call", "put"))
        self.assertAlmostEqual(
            call - put, 110 * math.exp(-0.025 * 1.5) - 103 * math.exp(0.01 * 1.5)
        )

    def test_expiry_and_deterministic_limit(self):
        self.assertEqual(black_scholes("put", 90, 100, 0, 0.04, 0.01, 0.25), 10)
        self.assertAlmostEqual(
            black_scholes("call", 100, 101, 1, 0.05, 0.01, 0),
            100 * math.exp(-0.01) - 101 * math.exp(-0.05),
        )
        with self.assertRaises(ValueError):
            black_scholes("call", 100, 100, -1, 0.05, 0, 0.2)
