import asyncio
import unittest

from app.services.reservations import calculate_monthly_revenue, calculate_total_revenue


class RevenueDatabaseTests(unittest.TestCase):
    def test_seeded_revenue_and_tenant_ownership(self):
        asyncio.run(self._run())

    async def _run(self):
        from app.core.database_pool import db_pool

        try:
            march = await calculate_monthly_revenue("prop-001", "tenant-a", 2024, 3)
            self.assertEqual(march["total_revenue_exact"], "2250.000")
            self.assertEqual(march["total_revenue"], "2250.00")
            self.assertEqual(march["reservations_count"], 4)
            self.assertEqual(march["timezone"], "Europe/Paris")

            february = await calculate_monthly_revenue("prop-001", "tenant-a", 2024, 2)
            self.assertEqual(february["total_revenue_exact"], "0.000")
            self.assertEqual(february["reservations_count"], 0)

            all_time = await calculate_total_revenue("prop-001", "tenant-a")
            self.assertEqual(all_time["total_revenue_exact"], "2250.000")
            self.assertEqual(all_time["reservations_count"], 4)

            foreign = await calculate_monthly_revenue("prop-002", "tenant-b", 2024, 3)
            self.assertIsNone(foreign)
        finally:
            await db_pool.close()


if __name__ == "__main__":
    unittest.main()
