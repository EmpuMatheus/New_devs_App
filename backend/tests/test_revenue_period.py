import unittest
from datetime import datetime, timezone
from decimal import Decimal

from app.services.reservations import (
    RevenueConfigurationError,
    format_amounts,
    month_bounds_utc,
    year_bounds_utc,
)


class RevenuePeriodTests(unittest.TestCase):
    def test_paris_march_2024_uses_dst_aware_boundaries(self):
        start, end = month_bounds_utc(2024, 3, "Europe/Paris")
        self.assertEqual(start, datetime(2024, 2, 29, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 3, 31, 22, 0, tzinfo=timezone.utc))

    def test_new_york_march_2024_boundaries(self):
        start, end = month_bounds_utc(2024, 3, "America/New_York")
        self.assertEqual(start, datetime(2024, 3, 1, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 4, 1, 4, 0, tzinfo=timezone.utc))

    def test_december_rolls_into_next_year(self):
        start, end = month_bounds_utc(2024, 12, "Europe/Paris")
        self.assertEqual(start, datetime(2024, 11, 30, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc))

    def test_annual_boundaries_use_property_timezone(self):
        start, end = year_bounds_utc(2024, "Europe/Paris")
        self.assertEqual(start, datetime(2023, 12, 31, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc))

    def test_invalid_timezone_is_controlled_error(self):
        with self.assertRaises(RevenueConfigurationError):
            month_bounds_utc(2024, 3, "Not/A_Timezone")
        with self.assertRaises(RevenueConfigurationError):
            month_bounds_utc(2024, 3, "")

    def test_invalid_month_is_rejected(self):
        with self.assertRaises(ValueError):
            month_bounds_utc(2024, 13, "Europe/Paris")

    def test_precision_is_aggregated_before_rounding(self):
        exact, display = format_amounts(Decimal("1000.000"))
        self.assertEqual(exact, "1000.000")
        self.assertEqual(display, "1000.00")

        per_row_rounded = (
            Decimal("333.333").quantize(Decimal("0.01"))
            + Decimal("333.333").quantize(Decimal("0.01"))
            + Decimal("333.334").quantize(Decimal("0.01"))
        )
        self.assertEqual(str(per_row_rounded), "999.99")

    def test_half_up_display_rounding(self):
        exact, display = format_amounts(Decimal("1234.565"))
        self.assertEqual(exact, "1234.565")
        self.assertEqual(display, "1234.57")


if __name__ == "__main__":
    unittest.main()
