import asyncio
import unittest
from uuid import UUID

from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError

from test_personal_context import PostgresAPITestCase
from test_space_tenancy import upgrade_database
from app.iam.models import User
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.repositories.space_repository import SpaceRepository
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.domain.models.value_objects.space_access import SpaceRole
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from app.wine_cellar.applications.inventory_excel_service import WineInventoryExcelService
from app.shared.quota_policy import QuotaExceededError, can_create_space, cellar_limit


class QuotaPolicyTests(unittest.TestCase):
    def test_courtesy_slots_and_purchased_extra_types(self):
        self.assertFalse(can_create_space([("COLLECTOR", "FREE")], 0, "COLLECTOR"))
        self.assertTrue(can_create_space([("COLLECTOR", "FREE")], 0, "BUSINESS"))
        self.assertTrue(can_create_space([("COLLECTOR", "FREE")], 1, "COLLECTOR"))
        self.assertFalse(can_create_space([("COLLECTOR", "FREE")] * 2, 1, "COLLECTOR"))
        self.assertTrue(can_create_space([("COLLECTOR", "FREE")] * 2, 1, "BUSINESS"))
        self.assertEqual(cellar_limit("FREE", 2), 3)
        self.assertEqual(cellar_limit("PRO", 2), 5)


class ResourceQuotaTests(PostgresAPITestCase):
    extra_spaces_allowance = 0
    extra_cellars_allowance = 0

    async def space(self, purpose="COLLECTOR", user_id=1):
        response = await self.client.post("/api/v1/spaces", json={"name": purpose, "space_type": purpose}, headers=self.headers(user_id))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def item(self, cellar, quantity=1, name="Vino"):
        return await self.client.post(
            "/api/v1/wine-items", json={"wine_cellar_id": cellar["id"], "name": name, "quantity": quantity}, headers=self.headers(),
        )

    async def extra_cellars(self, space, extra=1, plan="FREE"):
        from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM
        from sqlalchemy import update
        async with self.sessions() as session:
            stored = await session.get(SpaceORM, UUID(space["id"]))
            stored.extra_cellars_allowance = extra
            stored.subscription_plan = plan
            if plan == "FREE":
                await session.execute(update(ActiveSubscriptionORM).where(ActiveSubscriptionORM.space_id == stored.id).values(status="EXPIRED"))
            await session.commit()
        if plan == "PRO":
            await self.grant_pro(space)

    def assert_quota(self, response, code):
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"]["code"], code)

    async def test_default_account_has_one_free_space_of_each_type(self):
        await self.space()
        response = await self.client.post("/api/v1/user/onboarding", json={"name": "Otro", "space_type": "COLLECTOR"}, headers=self.headers())
        self.assert_quota(response, "SPACE_LIMIT_REACHED")
        await self.space("BUSINESS")
        response = await self.client.post("/api/v1/spaces", json={"name": "Otro", "space_type": "BUSINESS"}, headers=self.headers())
        self.assert_quota(response, "SPACE_LIMIT_REACHED")
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()
        self.assertEqual(context["account_quota"], {
            "extra_spaces_allowance": 0, "current_spaces": 2, "max_spaces": 2, "remaining_spaces": 0,
            "can_create_collector": False, "can_create_business": False,
        })
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(SpaceORM)), 2)
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 2)

    async def test_purchased_extra_slot_allows_repeat_type_but_not_unlimited_repeats(self):
        async with self.sessions() as session:
            user = await session.get(User, 1)
            user.extra_spaces_allowance = 1
            await session.commit()
        await self.space()
        await self.space()
        response = await self.client.post("/api/v1/spaces", json={"name": "Tercero"}, headers=self.headers())
        self.assert_quota(response, "SPACE_LIMIT_REACHED")
        await self.space("BUSINESS")
        response = await self.client.post("/api/v1/spaces", json={"name": "Cuarto"}, headers=self.headers())
        self.assert_quota(response, "SPACE_LIMIT_REACHED")

    async def test_shared_memberships_do_not_consume_personal_space_slots(self):
        shared = await self.space(user_id=2)
        async with self.sessions() as session:
            session.add(SpaceMemberORM(space_id=UUID(shared["id"]), user_id=1, role=SpaceRole.WAITER))
            await session.commit()
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()
        self.assertEqual(context["account_quota"]["current_spaces"], 0)
        await self.space()

    async def test_free_cellar_default_counts_and_addons_extend_it(self):
        space = await self.space()
        body = {"space_id": space["id"], "name": "Extra"}
        response = await self.client.post("/api/v1/wine-cellars", json=body, headers=self.headers())
        self.assert_quota(response, "CELLAR_LIMIT_REACHED")
        await self.extra_cellars(space, 1)
        response = await self.client.post("/api/v1/wine-cellars", json=body, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.client.post(f"/api/v1/spaces/{space['id']}/wine-cellars", json={"name": "Tercera"}, headers=self.headers())
        self.assert_quota(response, "CELLAR_LIMIT_REACHED")
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()
        self.assertEqual(context["spaces"][0]["quotas"]["cellars"], {"used": 2, "limit": 2, "remaining": 0})

    async def test_pro_cellar_base_is_three_plus_purchased_allowance(self):
        space = await self.space()
        await self.extra_cellars(space, 1, "PRO")
        for _ in range(3):
            await self.create_cellar(space)
        response = await self.client.post(f"/api/v1/spaces/{space['id']}/wine-cellars", json={"name": "Quinta"}, headers=self.headers())
        self.assert_quota(response, "CELLAR_LIMIT_REACHED")

    async def test_concurrent_cellar_creation_respects_the_last_slot(self):
        space = await self.space()
        await self.extra_cellars(space, 1)
        responses = await asyncio.gather(*[
            self.client.post("/api/v1/wine-cellars", json={"space_id": space["id"], "name": "Extra"}, headers=self.headers()) for _ in range(2)
        ])
        self.assertEqual(sorted(response.status_code for response in responses), [201, 403])
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 2)

    async def test_collector_counts_bottles_across_every_cellar_and_updates(self):
        space = await self.space()
        await self.extra_cellars(space, 1)
        second = await self.create_cellar(space)
        first_item = await self.item(space["default_wine_cellar"], 30)
        self.assertEqual(first_item.status_code, 201)
        self.assertEqual((await self.item(second, 20)).status_code, 201)
        self.assert_quota(await self.item(second, 1), "ITEM_LIMIT_REACHED")
        path = f"/api/v1/wine-cellars/{space['default_wine_cellar']['id']}/inventory/{first_item.json()['id']}"
        response = await self.client.patch(path, json={"quantity": 31}, headers=self.headers())
        self.assert_quota(response, "ITEM_LIMIT_REACHED")
        response = await self.client.patch(path, json={"quantity": 29}, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.item(second, 1)).status_code, 201)
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()["spaces"][0]
        self.assertEqual(context["quotas"]["bottles"], {"used": 50, "limit": 50, "remaining": 0})
        self.assertIsNone(context["quotas"]["skus"]["limit"])

    async def test_concurrent_inventory_inserts_cannot_cross_fifty_bottles(self):
        cellar = (await self.space())["default_wine_cellar"]
        self.assertEqual((await self.item(cellar, 49)).status_code, 201)
        responses = await asyncio.gather(self.item(cellar), self.item(cellar))
        self.assertEqual(sorted(response.status_code for response in responses), [201, 403])
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.sum(WineInventoryItemORM.quantity))), 50)

    async def test_business_counts_each_item_including_zero_stock_and_repeated_names(self):
        space = await self.space("BUSINESS")
        cellar = space["default_wine_cellar"]
        for _ in range(25):
            self.assertEqual((await self.item(cellar, 100, "Misma etiqueta")).status_code, 201)
        self.assert_quota(await self.item(cellar, 0, "Misma etiqueta"), "ITEM_LIMIT_REACHED")
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()["spaces"][0]
        self.assertEqual(context["quotas"]["skus"], {"used": 25, "limit": 25, "remaining": 0})
        self.assertEqual(context["quotas"]["bottles"]["used"], 2500)
        self.assertIsNone(context["quotas"]["bottles"]["limit"])

    async def test_pro_inventory_does_not_apply_free_limits(self):
        collector = await self.space()
        await self.extra_cellars(collector, 0, "PRO")
        self.assertEqual((await self.item(collector["default_wine_cellar"], 1000)).status_code, 201)
        business = await self.space("BUSINESS")
        await self.extra_cellars(business, 0, "PRO")
        rows = [["id", "wine_name", "wine_type", "age_years", "quantity"]] + [["", f"SKU {i}", "", "", 1] for i in range(26)]
        service = WineInventoryExcelService()
        async with self.sessions() as session:
            result = await service.import_inventory(session, UUID(business["default_wine_cellar"]["id"]), service._build_xlsx(rows, sheet_name="inventory"))
            self.assertEqual(result.created, 26)

    async def test_excel_cannot_bypass_quotas_and_rolls_back_whole_file(self):
        cellar = (await self.space())["default_wine_cellar"]
        original = await self.item(cellar, 49)
        self.assertEqual(original.status_code, 201)
        service = WineInventoryExcelService()
        headers = ["id", "wine_name", "wine_type", "age_years", "quantity"]
        rows = [headers, ["", "Nuevo 1", "", "", 1], ["", "Nuevo 2", "", "", 1]]
        async with self.sessions() as session:
            with self.assertRaises(QuotaExceededError) as caught:
                await service.import_inventory(session, UUID(cellar["id"]), service._build_xlsx(rows, sheet_name="inventory"))
            self.assertEqual(caught.exception.code, "ITEM_LIMIT_REACHED")
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineInventoryItemORM)), 1)
        # Evaluate the final file balance, not a transient row-by-row overage.
        rows = [headers, ["", "Reemplazo", "", "", 50], [original.json()["id"], "Original", "", "", 0]]
        async with self.sessions() as session:
            result = await service.import_inventory(session, UUID(cellar["id"]), service._build_xlsx(rows, sheet_name="inventory"))
            self.assertEqual((result.created, result.updated), (1, 1))

    async def test_existing_over_quota_data_can_be_reduced_but_not_grown(self):
        space = await self.space()
        await self.extra_cellars(space, 0, "PRO")
        response = await self.item(space["default_wine_cellar"], 100)
        await self.extra_cellars(space, 0, "FREE")
        path = f"/api/v1/wine-cellars/{space['default_wine_cellar']['id']}/inventory/{response.json()['id']}"
        self.assertEqual((await self.client.patch(path, json={"quantity": 99}, headers=self.headers())).status_code, 200)
        self.assertEqual((await self.client.patch(path, json={"name": "Actualizado"}, headers=self.headers())).status_code, 200)
        self.assert_quota(await self.client.patch(path, json={"quantity": 100}, headers=self.headers()), "ITEM_LIMIT_REACHED")

    async def test_client_cannot_grant_allowances_in_creation_payload(self):
        response = await self.client.post("/api/v1/spaces", json={"name": "Casa", "extra_cellars_allowance": 100}, headers=self.headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["extra_cellars_allowance"], 0)
        response = await self.client.post("/api/v1/wine-cellars", json={"space_id": response.json()["id"], "name": "No"}, headers=self.headers())
        self.assert_quota(response, "CELLAR_LIMIT_REACHED")

    async def test_rename_does_not_overwrite_a_concurrent_plan_and_allowance_change(self):
        space = await self.space()
        async with self.sessions() as session:
            repository = SpaceRepository(session)
            stale = await repository.find_by_id(UUID(space["id"]))
            self.assertEqual(stale.extra_cellars_allowance, 0)
            await self.extra_cellars(space, 2, "PRO")
            saved = await repository.rename(stale.id, "Nuevo nombre")
            self.assertEqual(saved.extra_cellars_allowance, 2)
            self.assertEqual(saved.subscription_plan.value, "PRO")

    async def test_allowances_are_nonnegative_database_constraints(self):
        space = await self.space()
        for model, primary_key, field in ((User, 1, "extra_spaces_allowance"), (SpaceORM, UUID(space["id"]), "extra_cellars_allowance")):
            async with self.sessions() as session:
                stored = await session.get(model, primary_key)
                setattr(stored, field, -1)
                with self.assertRaises(IntegrityError):
                    await session.commit()

    async def test_migration_preserves_data_and_normalizes_legacy_paid_plan(self):
        space = await self.space("BUSINESS")
        async with self.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE users DROP COLUMN extra_spaces_allowance"))
            await connection.execute(text("ALTER TABLE spaces DROP COLUMN extra_cellars_allowance"))
            await connection.execute(text("ALTER TABLE spaces DROP CONSTRAINT space_subscription_plan"))
            await connection.execute(text("ALTER TABLE spaces ALTER COLUMN subscription_plan TYPE VARCHAR(8)"))
            await connection.execute(text("ALTER TABLE spaces ADD CONSTRAINT space_subscription_plan CHECK (subscription_plan IN ('FREE','PRO','BUSINESS'))"))
            await connection.execute(text("UPDATE spaces SET subscription_plan='BUSINESS'"))
            await connection.run_sync(upgrade_database)
        async with self.sessions() as session:
            self.assertEqual((await session.get(User, 1)).extra_spaces_allowance, 0)
            stored = await session.get(SpaceORM, UUID(space["id"]))
            self.assertEqual(stored.subscription_plan.value, "PRO")
            self.assertEqual(stored.space_type.value, "BUSINESS")
            self.assertEqual(stored.extra_cellars_allowance, 0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 1)
