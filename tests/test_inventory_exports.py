import base64
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
import re
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4
import zlib

from openpyxl import load_workbook
from sqlalchemy import select, update

from app.core.config import settings
from app.core.security import create_access_token
from app.device.domain.models.value_objects.space_access import SpaceRole
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.iam.models import User
from app.wine_cellar.applications.inventory_excel_service import InventoryExcelError, WineInventoryExcelService, XLSX_MIME_TYPE
from app.wine_cellar.domain.models.inventory_export import InventoryExportData
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from app.wine_cellar.infrastructure.reporting.inventory_report_renderer import filename, render_pdf, render_xlsx
from test_personal_context import PostgresAPITestCase


PATH = "/api/v1/inventory/export"


def pdf_content(data):
    """Decode ReportLab page streams for structural/text checks without a test-only PDF dependency."""
    output = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            output.append(zlib.decompress(raw.strip()))
        except zlib.error:
            try:
                output.append(zlib.decompress(base64.a85decode(raw.strip(), adobe=True)))
            except (ValueError, zlib.error):
                pass
    return b"\n".join(output)


class InventoryReportTests(unittest.TestCase):
    def data(self, *, count=1, scoped=True, purpose="COLLECTOR"):
        return InventoryExportData(
            space_id=uuid4(), space_name='Mi colección\r\n"<test>', purpose=purpose,
            cellar_id=uuid4() if scoped else None, cellar_name="Cava Perú" if scoped else None,
            generated_at=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc),
            items=[{"id": uuid4(), "wine_name": f"VINO_{index:04d}", "winery": "Bodega Perú & <b>", "vintage": "2020",
                    "quantity": index, "cellar_name": "Cava Perú", "wine_type": "Syrah", "age_years": None,
                    "physical_location": "Estante A", "purchase_price": Decimal("10.50"), "sale_price": Decimal("15.00"),
                    "country": "Perú", "consumption_window": "2026–2030", "tasting_notes": "Notas", "company_notes": "Internas",
                    "would_buy_again": False} for index in range(count)],
        )

    def test_xlsx_has_context_styling_numeric_values_and_compatible_import_sheet(self):
        data = self.data()
        data.items[0]["wine_name"] = '=HYPERLINK("https://example.com")'
        data.items[0]["company_notes"] = "Control\x01text"
        raw = render_xlsx(data)
        book = load_workbook(BytesIO(raw), data_only=False)
        self.assertEqual(book.sheetnames, ["Inventario", "inventory"])
        report = book["Inventario"]
        self.assertEqual(report["B3"].value, data.cellar_name)
        self.assertEqual(report["B9"].data_type, "s")
        self.assertTrue(report["B9"].value.startswith("=HYPERLINK"))
        self.assertEqual(report.freeze_panes, "C9")
        headers = {cell.value: cell.column for cell in report[8]}
        self.assertEqual(report.cell(9, headers["Precio pagado"]).value, 10.5)
        self.assertIs(report.cell(9, headers["¿Volvería a comprar?"]).value, False)
        self.assertEqual(report.cell(9, headers["Notas internas"]).value, "Controltext")
        self.assertNotIn("Precio de venta", headers)
        self.assertEqual(book["inventory"]["B2"].data_type, "s")
        service = WineInventoryExcelService()
        sheet, rows = service._extract_sheet_rows(BytesIO(raw))
        parsed = service._parse_inventory_rows(rows)
        self.assertEqual(sheet, "inventory")
        self.assertEqual(parsed[0].item_id, data.items[0]["id"])
        self.assertEqual(parsed[0].wine_name, data.items[0]["wine_name"])
        self.assertIsNone(parsed[0].age_years)
        book.close()

    def test_business_fields_and_space_report_cannot_be_imported_accidentally(self):
        raw = render_xlsx(self.data(scoped=False, purpose="BUSINESS"))
        book = load_workbook(BytesIO(raw))
        self.assertEqual(book.sheetnames, ["Inventario"])
        headers = [cell.value for cell in book.active[8]]
        self.assertIn("Costo unitario", headers)
        self.assertIn("Precio de venta", headers)
        self.assertIn("Lote / Factura", headers)
        service = WineInventoryExcelService()
        _, rows = service._extract_sheet_rows(BytesIO(raw))
        with self.assertRaises(InventoryExcelError):
            service._parse_inventory_rows(rows)
        book.close()

    def test_empty_reports_and_safe_filenames(self):
        data = self.data(count=0)
        raw = render_pdf(data)
        self.assertTrue(raw.startswith(b"%PDF-"))
        self.assertIn(b"Sin", pdf_content(raw))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", raw)), 1)
        raw = render_xlsx(data)
        service = WineInventoryExcelService()
        _, rows = service._extract_sheet_rows(BytesIO(raw))
        self.assertEqual(service._parse_inventory_rows(rows), [])
        name = filename(data, "pdf")
        self.assertRegex(name, r"^[a-zA-Z0-9.-]+\.pdf$")
        self.assertIn("20261119", name)

    def test_pdf_paginate_repeat_headers_and_escape_user_markup(self):
        data = self.data(count=120, purpose="BUSINESS")
        raw = render_pdf(data)
        pages = len(re.findall(rb"/Type\s*/Page\b", raw))
        self.assertGreater(pages, 1)
        content = pdf_content(raw)
        self.assertIn(b"VINO_0000", content)
        self.assertIn(b"VINO_0119", content)
        self.assertGreaterEqual(content.count(b"Nombre del vino"), pages)
        self.assertIn(b"/ToUnicode", raw)  # Embedded font supports accents independently of OS fonts.


class InventoryExportAPITests(PostgresAPITestCase):
    async def create_named_item(self, cellar, name, user_id=1):
        response = await self.client.post(
            f"/api/v1/wine-cellars/{cellar['id']}/inventory",
            json={"name": name, "quantity": 1, "winery": "Bodega", "vintage": "2020", "purchase_price": "10.50", "tasting_notes": "Preservar notas"},
            headers=self.headers(user_id),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def download(self, space, *, cellar=None, format="xlsx", user_id=1, headers=None):
        params = {"space_id": space["id"], "format": format}
        if cellar:
            params["cellar_id"] = cellar["id"]
        return await self.client.get(PATH, params=params, headers=self.headers(user_id) if headers is None else headers)

    async def test_both_formats_filter_space_and_cellar_without_tenant_leaks(self):
        own = await self.create_space("Propio")
        second = await self.create_cellar(own)
        other = await self.create_space("Otro")
        foreign = await self.create_space("Ajeno", user_id=2)
        await self.create_named_item(own["default_wine_cellar"], "OWN_FIRST")
        await self.create_named_item(second, "OWN_SECOND")
        await self.create_named_item(other["default_wine_cellar"], "OTHER_SPACE_ONLY")
        await self.create_named_item(foreign["default_wine_cellar"], "FOREIGN_SECRET", user_id=2)
        for format in ("xlsx", "pdf"):
            for scope in (None, own["default_wine_cellar"]):
                response = await self.download(own, cellar=scope, format=format)
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assertEqual(response.headers["content-type"], XLSX_MIME_TYPE if format == "xlsx" else "application/pdf")
                self.assertIn(f'.{format}"', response.headers["content-disposition"])
                self.assertEqual(response.headers["cache-control"], "private, no-store")
                if format == "xlsx":
                    book = load_workbook(BytesIO(response.content))
                    values = [str(cell.value) for row in book["Inventario"].iter_rows() for cell in row if cell.value is not None]
                    text = " ".join(values)
                    self.assertEqual("inventory" in book.sheetnames, scope is not None)
                    book.close()
                else:
                    text = pdf_content(response.content).decode("latin1")
                self.assertIn("OWN_FIRST", text)
                self.assertEqual("OWN_SECOND" in text, scope is None)
                self.assertNotIn("OTHER_SPACE_ONLY", text)
                self.assertNotIn("FOREIGN_SECRET", text)

    async def test_authorization_cross_space_cellars_and_read_only_members(self):
        own = await self.create_space()
        another = await self.create_space("Otro propio")
        foreign = await self.create_space(user_id=2)
        for format in ("xlsx", "pdf"):
            for scope in (another["default_wine_cellar"], foreign["default_wine_cellar"], {"id": str(uuid4())}):
                response = await self.download(own, cellar=scope, format=format)
                self.assertEqual(response.status_code, 404, response.text)
            response = await self.download(foreign, format=format)
            self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual((await self.download(own, format=format, headers={})).status_code, 401)
        async with self.sessions() as session:
            session.add(SpaceMemberORM(space_id=UUID(own["id"]), user_id=3, role=SpaceRole.WAITER))
            await session.commit()
        self.assertEqual((await self.download(own, user_id=3)).status_code, 200)
        async with self.sessions() as session:
            await session.execute(update(User).where(User.id == 3).values(is_active=False))
            await session.execute(update(User).where(User.id == 2).values(is_superuser=True))
            await session.commit()
        self.assertEqual((await self.download(own, user_id=3)).status_code, 401)
        self.assertEqual((await self.download(own, user_id=2)).status_code, 403)
        self.assertEqual((await self.download(own, headers={"Authorization": "Bearer invalid"})).status_code, 401)
        refresh = create_access_token({"sub": "1", "type": "refresh"})
        self.assertEqual((await self.download(own, headers={"Authorization": f"Bearer {refresh}"})).status_code, 401)

    async def test_validation_limits_render_errors_and_cors_headers(self):
        own = await self.create_space()
        response = await self.download(own, format="csv")
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.client.get(PATH, headers=self.headers())).status_code, 422)
        self.assertEqual((await self.download({"id": "invalid"})).status_code, 422)
        response = await self.client.get(PATH, params={"space_id": own["id"]}, headers={**self.headers(), "Origin": (settings.CORS_ORIGINS_LIST or ["http://localhost:4200"])[0]})
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertIn("Content-Disposition", response.headers["access-control-expose-headers"])
        await self.create_named_item(own["default_wine_cellar"], "ONE")
        await self.create_named_item(own["default_wine_cellar"], "TWO")
        with patch("app.wine_cellar.applications.inventory_export_service.MAX_EXPORT_ITEMS", 1):
            self.assertEqual((await self.download(own)).status_code, 413)
        with patch("app.wine_cellar.interfaces.rest.controllers.inventory_export_controller.render_pdf", side_effect=ValueError("SECRET_TRACE")):
            response = await self.download(own, format="pdf")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("SECRET_TRACE", response.text)

    async def test_legacy_template_export_and_new_cellar_workbook_round_trip(self):
        own = await self.create_space()
        cellar = own["default_wine_cellar"]
        item = await self.create_named_item(cellar, "ROUNDTRIP")
        base = f"/api/v1/wine-cellars/{cellar['id']}/inventory"
        template = await self.client.get(base + "/template", headers=self.headers())
        self.assertEqual(template.status_code, 200)
        service = WineInventoryExcelService()
        _, rows = service._extract_sheet_rows(BytesIO(template.content))
        self.assertEqual(len(service._parse_inventory_rows(rows)), 3)
        legacy = await self.client.get(base + "/export", headers=self.headers())
        self.assertEqual(legacy.status_code, 200)
        _, rows = service._extract_sheet_rows(BytesIO(legacy.content))
        self.assertEqual(service._parse_inventory_rows(rows)[0].item_id, UUID(item["id"]))
        exported = await self.download(own, cellar=cellar)
        self.assertEqual(exported.status_code, 200)
        with patch("app.wine_cellar.interfaces.rest.controllers.wine_cellar_controller.AsyncSessionLocal", self.sessions):
            response = await self.client.post(base + "/import", files={"file": ("report.xlsx", exported.content, XLSX_MIME_TYPE)}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(response.json()["created"], 0)
        async with self.sessions() as session:
            row = await session.scalar(select(WineInventoryItemORM).where(WineInventoryItemORM.id == UUID(item["id"])))
            self.assertEqual(row.tasting_notes, "Preservar notas")
            self.assertEqual(row.purchase_price, Decimal("10.50"))
