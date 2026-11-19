"""Verify the scalar European pricing baseline using independent numerical checks.

Reference values cover the ordinary call and put formulas. Put-call parity checks the
relative discounting of spot and strike, while expiry and zero-volatility cases exercise
the branch that avoids division by zero. All tests use explicit annual inputs and run
without market data.
"""

import math
import unittest

from modules.models.black_scholes import black_scholes


class BlackScholesTests(unittest.TestCase):
    """Check numerical values, financial identities and boundary behavior of the pricer.

    The cases use both option kinds, continuous dividend yield and a negative risk-free
    rate. Explicit formulas and reference prices give the tests an independent expected
    result instead of deriving it from another call to the same implementation.
    """

    def test_classic_call_and_put(self):
        """Match reference prices for a one-year at-the-money call and put.

        Use spot and strike of 100, a 5% risk-free rate, zero dividend yield and 20%
        volatility. Compare each per-share price with its independent reference to nine
        decimal places, checking both signs in the common pricing formula.
        """
        args = (100, 100, 1, 0.05, 0, 0.2)
        self.assertAlmostEqual(black_scholes("call", *args), 10.4505835722, places=9)
        self.assertAlmostEqual(black_scholes("put", *args), 5.5735260223, places=9)

    def test_put_call_parity_with_dividends_and_negative_rate(self):
        """Check put-call parity when dividends and a negative rate affect discounting.

        Price a call and put with identical strike and maturity. Their difference must
        equal spot discounted by the continuous dividend yield minus strike discounted by
        the risk-free rate. The signs of the two exponents are independently visible in the
        expected expression.
        """
        args = (110, 103, 1.5, -0.01, 0.025, 0.29)
        call, put = (black_scholes(kind, *args) for kind in ("call", "put"))
        self.assertAlmostEqual(
            call - put, 110 * math.exp(-0.025 * 1.5) - 103 * math.exp(0.01 * 1.5)
        )

    def test_expiry_and_deterministic_limit(self):
        """Check the payoff at expiry and the discounted limit at zero volatility.

        An in-the-money put expiring immediately must return intrinsic value. A
        deterministic call with positive time remaining must match discounted spot less
        discounted strike for the chosen inputs. A negative time to expiry must raise
        ValueError.
        """
        self.assertEqual(black_scholes("put", 90, 100, 0, 0.04, 0.01, 0.25), 10)
        self.assertAlmostEqual(
            black_scholes("call", 100, 101, 1, 0.05, 0.01, 0),
            100 * math.exp(-0.01) - 101 * math.exp(-0.05),
        )
        with self.assertRaises(ValueError):
            black_scholes("call", 100, 100, -1, 0.05, 0, 0.2)
