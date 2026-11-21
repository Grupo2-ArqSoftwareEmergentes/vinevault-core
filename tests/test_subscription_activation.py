import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import update

from app.device.domain.models.value_objects.space_access import SpaceRole, SubscriptionPlan
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.iam.models import User
from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM
from test_personal_context import PostgresAPITestCase


BASE = "/api/v1/subscriptions"


class SubscriptionActivationTests(PostgresAPITestCase):
    extra_spaces_allowance = 0
    extra_cellars_allowance = 0

    async def space(self, purpose="COLLECTOR", user_id=1):
        response = await self.client.post("/api/v1/spaces", json={"name": purpose, "space_type": purpose}, headers=self.headers(user_id))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def upgrade(self, space, user_id=1, confirm=True, **values):
        return await self.client.post(BASE + "/plan-change-requests", headers=self.headers(user_id), json={
            "space_id": space["id"], "idempotency_key": str(uuid4()),
            "confirm_simulated_payment": confirm, **values,
        })

    async def extra(self, user_id=1, confirm=True, **values):
        return await self.client.post(BASE + "/extra-space-requests", headers=self.headers(user_id), json={
            "idempotency_key": str(uuid4()), "confirm_simulated_payment": confirm, **values,
        })

    async def activate_upgrade(self, space, user_id=1, **values):
        response = await self.upgrade(space, user_id=user_id, confirm=True, **values)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def activate_extra(self, user_id=1, **values):
        response = await self.extra(user_id=user_id, confirm=True, **values)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def overview(self, user_id=1, **params):
        response = await self.client.get(BASE + "/overview", params=params, headers=self.headers(user_id))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def expire(self, subscription_id):
        async with self.sessions() as session:
            row = await session.get(ActiveSubscriptionORM, UUID(subscription_id))
            now = datetime.now(timezone.utc)
            row.started_at = now - timedelta(days=31)
            row.current_period_end = now - timedelta(seconds=1)
            await session.commit()

    async def test_activation_grants_pro_immediately_with_monthly_cycle_and_mrr(self):
        collector = await self.space()
        business = await self.space("BUSINESS")
        first = await self.activate_upgrade(collector, cellar_id=collector["default_wine_cellar"]["id"])
        self.assertEqual(first["status"], "FULFILLED")
        self.assertTrue(first["entitlements_applied"])
        self.assertEqual(first["payment_mode"], "SIMULATED")
        self.assertEqual(first["unit_amount"], "29.99")
        self.assertEqual(first["total_amount"], "29.99")
        subscription = first["subscription"]
        self.assertEqual(subscription["kind"], "UPGRADE_PRO")
        self.assertEqual(subscription["monthly_amount"], "29.99")
        self.assertTrue(subscription["auto_renews"])
        self.assertFalse(subscription["cancel_at_period_end"])
        start = datetime.fromisoformat(subscription["started_at"])
        end = datetime.fromisoformat(subscription["current_period_end"])
        self.assertEqual(end - start, timedelta(days=30))
        self.assertEqual(subscription["access_until"], subscription["current_period_end"])
        business_activated = await self.activate_upgrade(business)
        self.assertEqual(business_activated["subscription"]["monthly_amount"], "79.99")

        overview = await self.overview(space_id=collector["id"])
        self.assertEqual(overview["space"]["subscription_plan"], "PRO")
        self.assertEqual(overview["space"]["quotas"]["cellars"], {"used": 1, "limit": 3, "remaining": 2})
        self.assertIsNone(overview["space"]["quotas"]["bottles"]["limit"])
        self.assertEqual(overview["billing"]["monthly_recurring_total"], "109.98")
        self.assertEqual(overview["billing"]["next_cycle_monthly_total"], "109.98")
        self.assertEqual(len(overview["billing"]["active_subscriptions"]), 2)

        for name in ("Cava 2", "Cava 3"):
            self.assertEqual((await self.client.post(f"/api/v1/spaces/{collector['id']}/wine-cellars", json={"name": name}, headers=self.headers())).status_code, 201)
        response = await self.client.post(f"/api/v1/spaces/{collector['id']}/wine-cellars", json={"name": "Cava 4"}, headers=self.headers())
        self.assertEqual(response.status_code, 403)
        response = await self.client.post("/api/v1/wine-items", json={"wine_cellar_id": collector["default_wine_cellar"]["id"], "name": "PRO bottles", "quantity": 51}, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        business_overview = await self.overview(space_id=business["id"])
        self.assertIsNone(business_overview["space"]["quotas"]["skus"]["limit"])
        async with self.sessions() as session:
            self.assertEqual((await session.get(SpaceORM, UUID(collector["id"]))).subscription_plan, SubscriptionPlan.PRO)
            self.assertEqual((await session.get(SpaceORM, UUID(business["id"]))).subscription_plan, SubscriptionPlan.PRO)

        extra = await self.activate_extra(quantity=2)
        self.assertEqual(extra["subscription"]["monthly_amount"], "40.00")
        self.assertEqual(extra["subscription"]["quantity"], 2)
        overview = await self.overview()
        self.assertEqual(overview["account_quota"]["extra_spaces_allowance"], 2)
        self.assertEqual(overview["account_quota"]["max_spaces"], 4)
        self.assertEqual(overview["billing"]["monthly_recurring_total"], "149.98")
        self.assertEqual(len(overview["billing"]["active_subscriptions"]), 3)
        async with self.sessions() as session:
            self.assertEqual((await session.get(User, 1)).extra_spaces_allowance, 0)
        self.assertEqual((await self.client.post("/api/v1/spaces", json={"name": "Extra A", "space_type": "COLLECTOR"}, headers=self.headers())).status_code, 201)
        self.assertEqual((await self.client.post("/api/v1/spaces", json={"name": "Extra B", "space_type": "BUSINESS"}, headers=self.headers())).status_code, 201)
        response = await self.client.post("/api/v1/spaces", json={"name": "Extra C"}, headers=self.headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "SPACE_LIMIT_REACHED")

    async def test_cancel_pro_keeps_access_until_cycle_end_then_expires(self):
        own = await self.space()
        activated = await self.activate_upgrade(own)
        subscription_id = activated["subscription"]["id"]
        response = await self.client.post(f"{BASE}/{subscription_id}/cancel", headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        cancelled = response.json()
        self.assertTrue(cancelled["cancel_at_period_end"])
        self.assertFalse(cancelled["auto_renews"])
        self.assertEqual(cancelled["access_until"], activated["subscription"]["current_period_end"])
        self.assertIsNotNone(cancelled["cancelled_at"])
        overview = await self.overview(space_id=own["id"])
        self.assertEqual(overview["space"]["subscription_plan"], "PRO")
        self.assertEqual(overview["space"]["quotas"]["cellars"]["limit"], 3)
        self.assertIsNone(overview["space"]["quotas"]["bottles"]["limit"])
        self.assertEqual(overview["billing"]["monthly_recurring_total"], "29.99")
        self.assertEqual(overview["billing"]["next_cycle_monthly_total"], "0.00")
        self.assertEqual((await self.client.post(f"/api/v1/spaces/{own['id']}/wine-cellars", json={"name": "Cava 2"}, headers=self.headers())).status_code, 201)
        await self.expire(subscription_id)
        overview = await self.overview(space_id=own["id"])
        self.assertEqual(overview["space"]["subscription_plan"], "FREE")
        self.assertEqual(overview["space"]["quotas"]["cellars"]["limit"], 1)
        self.assertEqual(overview["billing"]["monthly_recurring_total"], "0.00")
        self.assertEqual(overview["billing"]["active_subscriptions"], [])
        self.assertEqual((await self.client.post(f"/api/v1/spaces/{own['id']}/wine-cellars", json={"name": "Cava 3"}, headers=self.headers())).status_code, 403)
        response = await self.client.post(f"{BASE}/{subscription_id}/cancel", headers=self.headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "SUBSCRIPTION_EXPIRED")

    async def test_cancel_extra_space_keeps_slots_until_cycle_end(self):
        await self.space()
        extra = await self.activate_extra(quantity=1)
        subscription_id = extra["subscription"]["id"]
        overview = await self.overview()
        self.assertEqual(overview["account_quota"]["extra_spaces_allowance"], 1)
        self.assertEqual(overview["billing"]["monthly_recurring_total"], "20.00")
        response = await self.client.post(f"{BASE}/{subscription_id}/cancel", headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        overview = await self.overview()
        self.assertEqual(overview["account_quota"]["extra_spaces_allowance"], 1)
        self.assertEqual(overview["billing"]["next_cycle_monthly_total"], "0.00")
        self.assertEqual((await self.client.post("/api/v1/spaces", json={"name": "Tercero", "space_type": "COLLECTOR"}, headers=self.headers())).status_code, 201)
        await self.expire(subscription_id)
        overview = await self.overview()
        self.assertEqual(overview["account_quota"]["extra_spaces_allowance"], 0)
        self.assertEqual(overview["account_quota"]["max_spaces"], 2)
        self.assertEqual(overview["billing"]["monthly_recurring_total"], "0.00")

    async def test_activation_permissions_idempotency_currency_and_ownership(self):
        own = await self.space()
        foreign = await self.space(user_id=2)
        async with self.sessions() as session:
            session.add(SpaceMemberORM(space_id=UUID(own["id"]), user_id=3, role=SpaceRole.WAITER))
            await session.commit()
        self.assertEqual((await self.upgrade(own, user_id=3)).status_code, 403)
        self.assertEqual((await self.upgrade(own, user_id=2)).status_code, 403)
        response = await self.upgrade(own, currency="USD")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "SIMULATED_ACTIVATION_REQUIRES_PEN")
        self.assertEqual((await self.upgrade(own, cellar_id=foreign["default_wine_cellar"]["id"])).status_code, 404)
        key = str(uuid4())
        first = await self.upgrade(own, idempotency_key=key)
        self.assertEqual(first.status_code, 201, first.text)
        repeated = await self.upgrade(own, idempotency_key=key)
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.json()["subscription"]["id"], first.json()["subscription"]["id"])
        self.assertEqual((await self.upgrade(own)).status_code, 409)
        concurrent_space = await self.space("BUSINESS")
        responses = await asyncio.gather(*[self.upgrade(concurrent_space) for _ in range(2)])
        self.assertEqual(sorted(r.status_code for r in responses), [201, 409])
        other_extra = await self.activate_extra(user_id=2)
        self.assertEqual((await self.client.post(f"{BASE}/{other_extra['subscription']['id']}/cancel", headers=self.headers())).status_code, 404)
        cancelled_id = first.json()["subscription"]["id"]
        self.assertEqual((await self.client.post(f"{BASE}/{cancelled_id}/cancel", headers=self.headers(3))).status_code, 403)
        self.assertEqual((await self.client.post(f"{BASE}/{uuid4()}/cancel", headers=self.headers())).status_code, 404)

    async def test_pending_mode_remains_compatible_and_has_no_benefits(self):
        own = await self.space()
        response = await self.upgrade(own, confirm=False)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "PENDING_PAYMENT")
        self.assertFalse(response.json()["entitlements_applied"])
        self.assertEqual(response.json()["payment_mode"], "NONE")
        self.assertIsNone(response.json()["subscription"])
        overview = await self.overview(space_id=own["id"])
        self.assertEqual(overview["space"]["subscription_plan"], "FREE")
        self.assertEqual(overview["billing"]["monthly_recurring_total"], "0.00")
        self.assertEqual((await self.client.post(f"/api/v1/spaces/{own['id']}/wine-cellars", json={"name": "No PRO"}, headers=self.headers())).status_code, 403)
