import asyncio
from dataclasses import replace
from decimal import Decimal
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, inspect, select, text, update

from app.core.security import create_access_token
from app.device.domain.models.value_objects.space_access import SpaceRole, SubscriptionPlan, SubscriptionStatus
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.iam.models import User
from app.shared.quota_policy import account_space_limit, cellar_limit, inventory_limit
from app.subscriptions.domain.catalog import EXTRA_SPACE_PRICES, PLANS, catalog, get_plan, require_analysis_feature
from app.subscriptions.domain.errors import SubscriptionError
from app.subscriptions.infrastructure.database.models import SubscriptionIntentORM
from app.subscriptions.interfaces.rest.resources.subscription_resources import CatalogResponse, ExtraSpaceRequest
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from test_personal_context import PostgresAPITestCase
from test_space_tenancy import upgrade_database


BASE = "/api/v1/subscriptions"


class SubscriptionCatalogTests(unittest.TestCase):
    def test_official_monthly_prices_and_no_invented_usd_upgrade(self):
        data = CatalogResponse.model_validate(catalog()).model_dump(mode="json")
        prices = {price["currency"]: price["amount"] for price in data["addons"][0]["prices"]}
        self.assertEqual(prices, {"USD": "5.00", "PEN": "20.00"})
        plans = {(plan["purpose"], plan["tier"]): plan for plan in data["plans"]}
        for purpose, amount in (("COLLECTOR", "29.99"), ("BUSINESS", "79.99")):
            self.assertEqual(plans[(purpose, "PRO")]["prices"], [{"currency": "PEN", "amount": amount, "interval": "MONTH"}])
            self.assertTrue(plans[(purpose, "FREE")]["ai_analysis_enabled"])
        self.assertEqual(data["plan_scope"], "SPACE")
        self.assertEqual(data["billing_mode"], "PREPARATORY")

    def test_quota_writers_and_catalog_share_limits(self):
        self.assertEqual(account_space_limit(0), 2)
        self.assertEqual(account_space_limit(3), 5)
        for (purpose, tier), plan in PLANS.items():
            self.assertEqual(cellar_limit(tier, 2, purpose), plan.limits.cellars + 2)
            resource, maximum = inventory_limit(tier, purpose)
            self.assertEqual(maximum, getattr(plan.limits, resource))
        self.assertEqual(inventory_limit("FREE", "COLLECTOR"), ("bottles", 50))
        self.assertEqual(inventory_limit("FREE", "BUSINESS"), ("skus", 25))
        disabled = replace(get_plan("COLLECTOR", "FREE"), ai_analysis_enabled=False)
        with patch("app.subscriptions.domain.catalog.get_plan", return_value=disabled), self.assertRaises(SubscriptionError) as error:
            require_analysis_feature("COLLECTOR", "FREE")
        self.assertEqual(error.exception.status_code, 403)

    def test_quantity_and_client_granted_entitlements_are_rejected(self):
        for quantity in (0, -1, 101, True, "2", 1.5):
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                ExtraSpaceRequest(idempotency_key=uuid4(), quantity=quantity)
        with self.assertRaises(ValidationError):
            ExtraSpaceRequest(idempotency_key=uuid4(), extra_spaces_allowance=100)


class SubscriptionAPITests(PostgresAPITestCase):
    extra_spaces_allowance = 0
    extra_cellars_allowance = 0

    async def space(self, purpose="COLLECTOR", user_id=1):
        response = await self.client.post("/api/v1/spaces", json={"name": purpose, "space_type": purpose}, headers=self.headers(user_id))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def upgrade(self, space, user_id=1, **values):
        return await self.client.post(BASE + "/plan-change-requests", headers=self.headers(user_id), json={
            "space_id": space["id"], "idempotency_key": str(uuid4()), **values,
        })

    async def extra(self, user_id=1, **values):
        return await self.client.post(BASE + "/extra-space-requests", headers=self.headers(user_id), json={
            "idempotency_key": str(uuid4()), **values,
        })

    async def test_catalog_and_overview_match_existing_context_and_real_usage(self):
        own = await self.space()
        await self.create_inventory(own["default_wine_cellar"])
        catalog_response = await self.client.get(BASE + "/catalog", headers=self.headers())
        self.assertEqual(catalog_response.status_code, 200, catalog_response.text)
        self.assertEqual(catalog_response.json()["addons"][0]["prices"][1]["amount"], "20.00")
        overview = await self.client.get(BASE + "/overview", params={"space_id": own["id"], "cellar_id": own["default_wine_cellar"]["id"]}, headers=self.headers())
        self.assertEqual(overview.status_code, 200, overview.text)
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()
        self.assertEqual(overview.json()["account_quota"], context["account_quota"])
        self.assertEqual(overview.json()["space"]["quotas"], context["spaces"][0]["quotas"])
        self.assertEqual(overview.json()["space"]["quotas"]["bottles"]["used"], 3)
        self.assertTrue(overview.json()["space"]["can_manage_subscription"])
        self.assertTrue(overview.json()["cellar"]["inherits_space_plan"])
        account_only = await self.client.get(BASE + "/overview", headers=self.headers())
        self.assertIsNone(account_only.json()["space"])

    async def test_both_upgrade_prices_and_pending_does_not_grant_any_quotas(self):
        collector, business = await self.space(), await self.space("BUSINESS")
        for space, amount in ((collector, "29.99"), (business, "79.99")):
            response = await self.upgrade(space, cellar_id=space["default_wine_cellar"]["id"])
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()["unit_amount"], amount)
            self.assertEqual(response.json()["total_amount"], amount)
            self.assertEqual(response.json()["status"], "PENDING_PAYMENT")
            self.assertEqual(response.json()["entitlement_scope"], "SPACE")
            self.assertFalse(response.json()["entitlements_applied"])
        extra = await self.extra(currency="USD", quantity=2)
        self.assertEqual(extra.status_code, 202, extra.text)
        self.assertEqual(extra.json()["unit_amount"], "5.00")
        self.assertEqual(extra.json()["total_amount"], "10.00")
        pen = await self.extra(currency="PEN", quantity=2)
        self.assertEqual(pen.json()["total_amount"], "40.00")
        async with self.sessions() as session:
            self.assertEqual((await session.get(User, 1)).extra_spaces_allowance, 0)
            for space in (collector, business):
                row = await session.get(SpaceORM, UUID(space["id"]))
                self.assertEqual(row.subscription_plan, SubscriptionPlan.FREE)
                self.assertEqual(row.extra_cellars_allowance, 0)
        response = await self.client.post("/api/v1/spaces", json={"name": "No granted slot"}, headers=self.headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "SPACE_LIMIT_REACHED")
        response = await self.client.post(f"/api/v1/spaces/{collector['id']}/wine-cellars", json={"name": "No PRO cellar"}, headers=self.headers())
        self.assertEqual(response.status_code, 403)
        response = await self.client.post("/api/v1/wine-items", json={"wine_cellar_id": collector["default_wine_cellar"]["id"], "name": "No PRO bottles", "quantity": 51}, headers=self.headers())
        self.assertEqual(response.status_code, 403)

    async def test_access_roles_and_space_cellar_isolation(self):
        own, another = await self.space(), await self.space("BUSINESS")
        foreign = await self.space(user_id=2)
        response = await self.client.get(BASE + "/overview", params={"space_id": foreign["id"]}, headers=self.headers())
        self.assertEqual(response.status_code, 403)
        response = await self.upgrade(foreign)
        self.assertEqual(response.status_code, 403)
        for cellar in (another["default_wine_cellar"], foreign["default_wine_cellar"]):
            response = await self.client.get(BASE + "/overview", params={"space_id": own["id"], "cellar_id": cellar["id"]}, headers=self.headers())
            self.assertEqual(response.status_code, 404)
            self.assertEqual((await self.upgrade(own, cellar_id=cellar["id"])).status_code, 404)
        async with self.sessions() as session:
            session.add(SpaceMemberORM(space_id=UUID(own["id"]), user_id=3, role=SpaceRole.WAITER))
            await session.execute(update(User).where(User.id == 2).values(is_superuser=True))
            await session.commit()
        response = await self.client.get(BASE + "/overview", params={"space_id": own["id"]}, headers=self.headers(3))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["space"]["can_manage_subscription"])
        self.assertFalse(response.json()["space"]["can_analyze"])
        self.assertEqual((await self.upgrade(own, user_id=3)).status_code, 403)
        self.assertEqual((await self.upgrade(own, user_id=2)).status_code, 403)
        # Account add-ons are owned by the caller, regardless of membership in somebody else's space.
        self.assertEqual((await self.extra(user_id=3)).status_code, 202)

    async def test_idempotency_concurrency_conflicts_and_private_request_history(self):
        own = await self.space()
        key = str(uuid4())
        responses = await asyncio.gather(*[self.upgrade(own, idempotency_key=key) for _ in range(2)])
        self.assertEqual([r.status_code for r in responses], [202, 202])
        self.assertEqual(responses[0].json()["id"], responses[1].json()["id"])
        conflict = await self.upgrade(own, idempotency_key=key, currency="USD")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual((await self.upgrade(own)).status_code, 409)
        extra_key = str(uuid4())
        responses = await asyncio.gather(*[self.extra(idempotency_key=extra_key, quantity=2) for _ in range(2)])
        self.assertEqual([r.status_code for r in responses], [202, 202])
        self.assertEqual(responses[0].json()["id"], responses[1].json()["id"])
        self.assertEqual((await self.extra(idempotency_key=extra_key, quantity=3)).status_code, 409)
        # Same key in another account is independent, and lists never include another payer's requests.
        other = await self.extra(user_id=2, idempotency_key=extra_key)
        self.assertEqual(other.status_code, 202)
        own_requests = await self.client.get(BASE + "/requests", headers=self.headers())
        other_requests = await self.client.get(BASE + "/requests", headers=self.headers(2))
        self.assertEqual(len(own_requests.json()), 2)
        self.assertEqual(len(other_requests.json()), 1)
        self.assertEqual(other_requests.json()[0]["id"], other.json()["id"])
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(SubscriptionIntentORM)), 3)

    async def test_request_rules_active_users_and_unsupported_prices(self):
        own = await self.space()
        response = await self.upgrade(own, currency="USD")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "CURRENCY_UNAVAILABLE")
        self.assertEqual((await self.extra(unit_amount="0.01")).status_code, 422)
        self.assertEqual((await self.extra(requester_user_id=2)).status_code, 422)
        self.assertEqual((await self.upgrade(own, target_plan="FREE")).status_code, 422)
        self.assertEqual((await self.client.get(BASE + "/overview", params={"cellar_id": own["default_wine_cellar"]["id"]}, headers=self.headers())).status_code, 422)
        async with self.sessions() as session:
            await session.execute(update(SpaceORM).where(SpaceORM.id == UUID(own["id"])).values(subscription_plan=SubscriptionPlan.PRO, subscription_status=SubscriptionStatus.EXPIRED))
            await session.commit()
        self.assertEqual((await self.upgrade(own)).status_code, 409)
        overview = await self.client.get(BASE + "/overview", params={"space_id": own["id"]}, headers=self.headers())
        self.assertEqual(overview.json()["space"]["subscription_status"], "EXPIRED")
        self.assertIsNone(overview.json()["space"]["quotas"]["bottles"]["limit"])
        refresh = create_access_token({"sub": "1", "type": "refresh"})
        for headers in ({}, {"Authorization": "Bearer invalid"}, {"Authorization": "Bearer " + refresh}):
            self.assertEqual((await self.client.get(BASE + "/catalog", headers=headers)).status_code, 401)
            self.assertEqual((await self.client.post(BASE + "/extra-space-requests", json={"idempotency_key": str(uuid4())}, headers=headers)).status_code, 401)
        async with self.sessions() as session:
            await session.execute(update(User).where(User.id == 1).values(is_active=False))
            await session.commit()
        self.assertEqual((await self.client.get(BASE + "/catalog", headers=self.headers())).status_code, 401)
        self.assertEqual((await self.extra()).status_code, 401)

    async def test_pending_upgrade_serializes_different_keys(self):
        own = await self.space()
        responses = await asyncio.gather(self.upgrade(own), self.upgrade(own))
        self.assertEqual(sorted(r.status_code for r in responses), [202, 409])

    async def test_ai_feature_policy_is_checked_without_changing_current_free_access(self):
        own = await self.space()
        disabled = replace(get_plan("COLLECTOR", "FREE"), ai_analysis_enabled=False)
        with patch("app.subscriptions.domain.catalog.get_plan", return_value=disabled):
            assistant = await self.client.post("/api/v1/assistant/chat", json={"space_id": own["id"], "message": "Stock?"}, headers=self.headers())
            analyze = await self.client.post("/api/v1/ai/analyze-stock", json={"wine_cellar_id": own["default_wine_cellar"]["id"]}, headers=self.headers())
        self.assertEqual(assistant.status_code, 403, assistant.text)
        self.assertEqual(assistant.json()["detail"]["code"], "PLAN_FEATURE_UNAVAILABLE")
        self.assertEqual(analyze.status_code, 403, analyze.text)
        self.assertEqual(analyze.json()["detail"]["code"], "PLAN_FEATURE_UNAVAILABLE")
        disabled_plans = {**PLANS, ("COLLECTOR", "FREE"): disabled}
        with patch("app.core.space_security.PLANS", disabled_plans):
            autocomplete = await self.client.post("/api/v1/inventory/ai-autocomplete", json={"wine_name": "Malbec"}, headers=self.headers())
        self.assertEqual(autocomplete.status_code, 403, autocomplete.text)

    async def test_migration_preserves_accounts_spaces_and_inventory(self):
        own = await self.space()
        item = await self.create_inventory(own["default_wine_cellar"])
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP TABLE subscription_intents"))
            await connection.run_sync(upgrade_database)
            await connection.run_sync(upgrade_database)
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            self.assertIn("subscription_intents", tables)
            self.assertEqual(await connection.scalar(text("SELECT version_num FROM alembic_version")), "20261119_subscription_intents")
        async with self.sessions() as session:
            self.assertEqual((await session.get(SpaceORM, UUID(own["id"]))).subscription_plan, SubscriptionPlan.FREE)
            self.assertEqual((await session.get(WineInventoryItemORM, UUID(item["id"]))).quantity, 3)
            self.assertEqual((await session.get(User, 1)).extra_spaces_allowance, 0)
        self.assertEqual((await self.upgrade(own)).status_code, 202)
