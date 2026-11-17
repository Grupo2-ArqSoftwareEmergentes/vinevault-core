import asyncio
import unittest
from decimal import Decimal
from uuid import UUID
from unittest.mock import patch

from sqlalchemy import select, func, text, inspect

from test_personal_context import PostgresAPITestCase
from test_space_tenancy import upgrade_database
from app.device.domain.models.value_objects.space_access import SpaceRole
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.wine_cellar.domain.models.wine_item_details import WineItemDetails
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from app.wine_cellar.infrastructure.database.models.stock_movement_orm import StockMovementORM
from app.wine_cellar.infrastructure.database.repositories.stock_movement_repository import StockMovementRepository
from app.wine_cellar.infrastructure.database.repositories.wine_inventory_repository import WineInventoryRepository
from app.wine_cellar.applications.inventory_excel_service import WineInventoryExcelService
from app.wine_cellar.interfaces.rest.resources.wine_inventory_request import CreateWineInventoryItemRequest, UpdateWineInventoryItemRequest
from pydantic import ValidationError


class WineItemValidationTests(unittest.TestCase):
    def test_minimal_and_legacy_requests_share_one_name(self):
        modern = CreateWineInventoryItemRequest(name="  Reserva  ", vintage=2020)
        self.assertEqual(modern.name, "Reserva")
        self.assertEqual(modern.vintage, "2020")
        self.assertIsNone(modern.sale_price)
        self.assertEqual(CreateWineInventoryItemRequest(wine_name="Reserva").name, modern.name)
        with self.assertRaises(ValidationError):
            CreateWineInventoryItemRequest(name="A", wine_name="B")

    def test_invalid_values_are_rejected_and_optional_nulls_are_allowed(self):
        for field, invalid in (
            ("vintage", "unknown"), ("vintage", True), ("purchase_price", "-0.01"),
            ("sale_price", "1.001"), ("alcohol_percentage", 101), ("rating", 101),
            ("rating", 0), ("body_slider", 6), ("min_stock_alert", -1),
            ("aroma_tags", [""]), ("name", "   "), ("quantity", -1),
        ):
            with self.subTest(field=field, invalid=invalid):
                with self.assertRaises(ValidationError):
                    CreateWineInventoryItemRequest.model_validate({"name": "Vino", field: invalid})
        request = CreateWineInventoryItemRequest(name="Vino", wine_type=None, age_years=None, aroma_tags=None, vintage="nv")
        self.assertEqual(request.vintage, "NV")
        self.assertIsNone(request.aroma_tags)
        for field in ("name", "quantity"):
            with self.assertRaises(ValidationError):
                UpdateWineInventoryItemRequest.model_validate({field: None})


class UnifiedWineItemTests(PostgresAPITestCase):
    async def create_item(self, cellar, body, user_id=1):
        response = await self.client.post(
            f"/api/v1/wine-cellars/{cellar['id']}/inventory", json=body, headers=self.headers(user_id),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def movement_url(self, cellar, item):
        return f"/api/v1/wine-cellars/{cellar['id']}/inventory/{item['id']}/movements"

    async def test_minimal_item_stores_optional_fields_as_sql_null(self):
        space = await self.create_space()
        item = await self.create_item(space["default_wine_cellar"], {"name": "Colección", "quantity": 3})
        self.assertEqual(item["name"], item["wine_name"])
        for field in WineItemDetails.model_fields:
            self.assertIsNone(item[field], field)
        async with self.sessions() as session:
            row = await session.get(WineInventoryItemORM, UUID(item["id"]))
            self.assertEqual(row.name, "Colección")
            self.assertTrue(await session.scalar(select(WineInventoryItemORM.aroma_tags.is_(None))))
            snapshot = await WineInventoryRepository(session).get_analysis_snapshot(UUID(space["default_wine_cellar"]["id"]))
            self.assertEqual(snapshot.inventory[0].wine_name, "Colección")
            self.assertIsNone(snapshot.inventory[0].age_years)
            self.assertIsNone(snapshot.inventory[0].wine_type)

    async def test_full_unified_details_round_trip_for_both_purposes(self):
        for purpose in ("COLLECTOR", "BUSINESS"):
            response = await self.client.post("/api/v1/spaces", json={"name": purpose, "space_type": purpose}, headers=self.headers())
            self.assertEqual(response.status_code, 201, response.text)
            cellar = response.json()["default_wine_cellar"]
            body = {
                "name": "Reserva", "winery": "Bodega Ejemplo", "vintage": "NV", "quantity": 12,
                "physical_location": "Estante A2", "country": "España", "region": "Rioja",
                "appellation": "DOCa Rioja", "wine_type": "Tempranillo", "bottle_format": "750ml",
                "aging": "Reserva", "alcohol_percentage": "13.50", "consumption_window": "2026-2032",
                "purchase_price": "19.99", "sale_price": "29.95", "min_stock_alert": 2,
                "supplier_name": "Distribuidor", "origin_type": "Proveedor", "purchase_date": "2026-11-01",
                "batch_invoice_number": "INV-001", "rating": "94", "body_slider": "4.5",
                "acidity_slider": "3", "tannins_slider": "4", "aroma_tags": ["Fruta", "Especias"],
                "occasion_notes": "Celebración", "company_notes": "Familia", "would_buy_again": True,
            }
            created = await self.create_item(cellar, body)
            response = await self.client.get(f"/api/v1/wine-cellars/{cellar['id']}/inventory", headers=self.headers())
            stored = response.json()[0]
            self.assertEqual(stored, created)
            for key, value in body.items():
                if key == "origin_type":
                    self.assertEqual(stored[key], "SUPPLIER")
                elif key in {"alcohol_percentage", "purchase_price", "sale_price", "rating", "body_slider", "acidity_slider", "tannins_slider"}:
                    self.assertEqual(Decimal(stored[key]), Decimal(value))
                else:
                    self.assertEqual(stored[key], value)

    async def test_partial_update_preserves_omitted_fields_and_clears_explicit_nulls(self):
        space = await self.create_space()
        cellar = space["default_wine_cellar"]
        item = await self.create_item(cellar, {"wine_name": "Legacy", "quantity": 5, "purchase_price": "10.10", "supplier_name": "Proveedor", "aroma_tags": ["Fruta"]})
        path = f"/api/v1/wine-cellars/{cellar['id']}/inventory/{item['id']}"
        response = await self.client.patch(path, json={"supplier_name": None, "sale_price": "20.20", "aroma_tags": None}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        self.assertEqual(updated["quantity"], 5)
        self.assertEqual(updated["purchase_price"], "10.10")
        self.assertIsNone(updated["supplier_name"])
        self.assertIsNone(updated["aroma_tags"])
        response = await self.client.put(path, json={"wine_name": "Renombrado", "wine_type": "Red", "age_years": 2, "quantity": 7}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Renombrado")
        self.assertEqual(response.json()["sale_price"], "20.20")

    async def test_stock_exit_records_reason_actor_notes_and_balance(self):
        space = await self.create_space()
        cellar = space["default_wine_cellar"]
        item = await self.create_item(cellar, {"name": "Reserva", "quantity": 5})
        url = self.movement_url(cellar, item)
        for reason in ("sale", "tasting", "breakage", "uncorking"):
            response = await self.client.post(url, json={"quantity": 1, "reason": reason, "notes": "  Con amigos  ", "user_id": 999}, headers=self.headers())
            self.assertEqual(response.status_code, 201, response.text)
            movement = response.json()
            self.assertEqual(movement["stock_before"] - movement["stock_after"], 1)
            self.assertEqual(movement["reason"], reason)
            self.assertEqual(movement["user_id"], 1)
            self.assertEqual(movement["notes"], "Con amigos")
        history = await self.client.get(url, headers=self.headers())
        self.assertEqual(len(history.json()), 4)
        async with self.sessions() as session:
            self.assertEqual((await session.get(WineInventoryItemORM, UUID(item["id"]))).quantity, 1)
        response = await self.client.post(url, json={"quantity": 2, "reason": "sale"}, headers=self.headers())
        self.assertEqual(response.status_code, 409)
        for quantity in (0, -1, True, "1"):
            response = await self.client.post(url, json={"quantity": quantity, "reason": "sale"}, headers=self.headers())
            self.assertEqual(response.status_code, 422)

    async def test_concurrent_stock_exits_cannot_oversell(self):
        cellar = (await self.create_space())["default_wine_cellar"]
        item = await self.create_item(cellar, {"name": "Última botella", "quantity": 1})
        responses = await asyncio.gather(*[
            self.client.post(self.movement_url(cellar, item), json={"quantity": 1, "reason": "sale"}, headers=self.headers())
            for _ in range(2)
        ])
        self.assertEqual(sorted(response.status_code for response in responses), [201, 409])
        async with self.sessions() as session:
            self.assertEqual((await session.get(WineInventoryItemORM, UUID(item["id"]))).quantity, 0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(StockMovementORM)), 1)

    async def test_failed_history_insert_rolls_back_stock(self):
        cellar = (await self.create_space())["default_wine_cellar"]
        item = await self.create_item(cellar, {"name": "Reserva", "quantity": 3})
        original = StockMovementRepository.save

        async def fail(repository, movement):
            await original(repository, movement)
            raise RuntimeError("movement failure")

        with patch.object(StockMovementRepository, "save", fail):
            with self.assertRaisesRegex(RuntimeError, "movement failure"):
                await self.client.post(self.movement_url(cellar, item), json={"quantity": 1, "reason": "tasting"}, headers=self.headers())
        async with self.sessions() as session:
            self.assertEqual((await session.get(WineInventoryItemORM, UUID(item["id"]))).quantity, 3)
            self.assertEqual(await session.scalar(select(func.count()).select_from(StockMovementORM)), 0)

    async def test_metadata_update_does_not_undo_concurrent_stock_exit(self):
        cellar = (await self.create_space())["default_wine_cellar"]
        item = await self.create_item(cellar, {"name": "Reserva", "quantity": 3})
        path = f"/api/v1/wine-cellars/{cellar['id']}/inventory/{item['id']}"
        responses = await asyncio.gather(
            self.client.post(self.movement_url(cellar, item), json={"quantity": 1, "reason": "sale"}, headers=self.headers()),
            self.client.patch(path, json={"supplier_name": "Actualizado"}, headers=self.headers()),
        )
        self.assertEqual(sorted(response.status_code for response in responses), [200, 201])
        async with self.sessions() as session:
            stored = await session.get(WineInventoryItemORM, UUID(item["id"]))
            self.assertEqual(stored.quantity, 2)
            self.assertEqual(stored.supplier_name, "Actualizado")

    async def test_inventory_clerk_can_record_movement_and_waiter_can_read_history(self):
        space = await self.create_space()
        cellar = space["default_wine_cellar"]
        item = await self.create_item(cellar, {"name": "Reserva", "quantity": 3})
        async with self.sessions() as session:
            session.add_all([
                SpaceMemberORM(space_id=UUID(space["id"]), user_id=2, role=SpaceRole.INVENTORY_CLERK),
                SpaceMemberORM(space_id=UUID(space["id"]), user_id=3, role=SpaceRole.WAITER),
            ])
            await session.commit()
        url = self.movement_url(cellar, item)
        response = await self.client.post(url, json={"quantity": 1, "reason": "sale"}, headers=self.headers(2))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["user_id"], 2)
        response = await self.client.get(url + "?limit=1", headers=self.headers(3))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    async def test_stock_movement_checks_cellar_scope_and_role(self):
        own = (await self.create_space())["default_wine_cellar"]
        foreign_space = await self.create_space(user_id=2)
        foreign = foreign_space["default_wine_cellar"]
        item = await self.create_item(foreign, {"name": "Ajeno", "quantity": 3}, user_id=2)
        body = {"quantity": 1, "reason": "sale"}
        self.assertEqual((await self.client.post(self.movement_url(own, item), json=body, headers=self.headers())).status_code, 404)
        self.assertEqual((await self.client.post(self.movement_url(foreign, item), json=body, headers=self.headers())).status_code, 403)
        async with self.sessions() as session:
            session.add(SpaceMemberORM(space_id=UUID(foreign_space["id"]), user_id=1, role=SpaceRole.WAITER))
            await session.commit()
        self.assertEqual((await self.client.post(self.movement_url(foreign, item), json=body, headers=self.headers())).status_code, 403)
        async with self.sessions() as session:
            self.assertEqual((await session.get(WineInventoryItemORM, UUID(item["id"]))).quantity, 3)

    async def test_excel_round_trip_handles_missing_type_and_age_without_erasing_details(self):
        cellar = (await self.create_space())["default_wine_cellar"]
        item = await self.create_item(cellar, {"name": "NV", "vintage": "NV", "quantity": 3, "purchase_price": "25.00"})
        async with self.sessions() as session:
            workbook = await WineInventoryExcelService().export_inventory(session, UUID(cellar["id"]))
        async with self.sessions() as session:
            result = await WineInventoryExcelService().import_inventory(session, UUID(cellar["id"]), workbook)
            self.assertEqual(result.updated, 1)
            stored = await session.get(WineInventoryItemORM, UUID(item["id"]))
            self.assertEqual(stored.purchase_price, Decimal("25.00"))
            self.assertEqual(stored.vintage, "NV")
            self.assertIsNone(stored.wine_type)
            self.assertIsNone(stored.age_years)

    async def test_deleting_space_with_movement_history_still_cascades(self):
        space = await self.create_space()
        cellar = space["default_wine_cellar"]
        item = await self.create_item(cellar, {"name": "Reserva", "quantity": 2})
        self.assertEqual((await self.client.post(self.movement_url(cellar, item), json={"quantity": 1, "reason": "uncorking"}, headers=self.headers())).status_code, 201)
        self.assertEqual((await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers())).status_code, 204)
        async with self.sessions() as session:
            for model in (WineInventoryItemORM, StockMovementORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 0)


class WineItemMigrationTests(PostgresAPITestCase):
    async def test_upgrade_preserves_legacy_inventory_name_and_stock(self):
        space = await self.create_space()
        item = await self.create_inventory(space["default_wine_cellar"])
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP TABLE wine_stock_movements"))
            for field in WineItemDetails.model_fields:
                if field not in {"wine_type", "age_years"}:
                    await connection.execute(text(f"ALTER TABLE wine_inventory_items DROP COLUMN {field}"))
            await connection.execute(text("ALTER TABLE wine_inventory_items RENAME COLUMN name TO wine_name"))
            await connection.execute(text("ALTER TABLE wine_inventory_items ALTER COLUMN wine_type SET NOT NULL"))
            await connection.execute(text("ALTER TABLE wine_inventory_items ALTER COLUMN age_years SET NOT NULL"))
            await connection.run_sync(upgrade_database)
        async with self.sessions() as session:
            stored = await session.get(WineInventoryItemORM, UUID(item["id"]))
            self.assertEqual(stored.name, "Reserva")
            self.assertEqual(stored.quantity, 3)
            self.assertEqual(stored.age_years, 2)
            self.assertIsNone(stored.sale_price)
        async with self.engine.begin() as connection:
            columns = await connection.run_sync(lambda sync: {column["name"] for column in inspect(sync).get_columns("wine_inventory_items")})
            self.assertIn("name", columns)
            self.assertNotIn("wine_name", columns)
