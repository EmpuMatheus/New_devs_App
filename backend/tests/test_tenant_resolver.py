import asyncio
import unittest

from app.core.tenant_resolver import TenantResolver


class TenantResolverTests(unittest.TestCase):
    def resolve(self, email, payload=None):
        return asyncio.run(
            TenantResolver.resolve_tenant_id(
                user_id="test-user",
                user_email=email,
                token_payload=payload,
            )
        )

    def test_known_sunset_user(self):
        self.assertEqual(self.resolve("sunset@propertyflow.com"), "tenant-a")

    def test_known_ocean_user(self):
        self.assertEqual(self.resolve("ocean@propertyflow.com"), "tenant-b")

    def test_trusted_root_claim(self):
        self.assertEqual(
            self.resolve("someone@example.com", {"tenant_id": "tenant-b"}),
            "tenant-b",
        )

    def test_trusted_app_metadata_claim(self):
        self.assertEqual(
            self.resolve(
                "someone@example.com",
                {"app_metadata": {"tenant_id": "tenant-a"}},
            ),
            "tenant-a",
        )

    def test_user_metadata_is_not_trusted(self):
        self.assertIsNone(
            self.resolve(
                "someone@example.com",
                {"user_metadata": {"tenant_id": "tenant-a"}},
            )
        )

    def test_unknown_user_gets_no_tenant(self):
        self.assertIsNone(self.resolve("unknown@example.com"))

    def test_missing_claim_gets_no_tenant(self):
        self.assertIsNone(self.resolve("someone@example.com", {}))

    def test_invalid_claim_is_rejected(self):
        self.assertIsNone(
            self.resolve("someone@example.com", {"tenant_id": "!!invalid!!"})
        )
        self.assertIsNone(
            self.resolve("someone@example.com", {"tenant_id": 123})
        )


if __name__ == "__main__":
    unittest.main()
