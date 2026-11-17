from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, BadZipFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.wine_cellar.infrastructure.database.models import WineInventoryItemORM
from app.wine_cellar.infrastructure.database.repositories import WineInventoryRepository
from app.shared.infrastructure.database.resource_quota_repository import ResourceQuotaRepository
from app.shared.quota_policy import validate_inventory_growth


XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(slots=True)
class InventoryImportResult:
    sheet_name: str
    total_rows: int
    created: int
    updated: int


@dataclass(slots=True)
class _ParsedInventoryRow:
    row_number: int
    item_id: UUID | None
    wine_name: str
    wine_type: str | None
    age_years: int | None
    quantity: int


class InventoryExcelError(ValueError):
    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or []


class WineInventoryExcelService:
    SHEET_NAME = "inventory"
    HEADERS = ("id", "wine_name", "wine_type", "age_years", "quantity")
    REQUIRED_HEADERS = ("wine_name", "wine_type", "age_years", "quantity")
    TEMPLATE_ROWS = (
        ("", "Cabernet Sauvignon Reserva", "Red", 5, 12),
        ("", "Chardonnay Blanco", "White", 2, 24),
        ("", "Rosé Brut", "Rosé", 1, 8),
    )

    async def export_inventory(self, session: AsyncSession, wine_cellar_id: UUID) -> bytes:
        repository = WineInventoryRepository(session)
        items = await repository.find_all_by_wine_cellar_id(wine_cellar_id)
        rows: list[list[Any]] = [list(self.HEADERS)]
        for item in items:
            rows.append(
                [
                    str(item.id),
                    item.wine_name,
                    item.wine_type,
                    item.age_years,
                    item.quantity,
                ]
            )
        return self._build_xlsx(rows, sheet_name=self.SHEET_NAME)

    def export_template(self) -> bytes:
        rows: list[list[Any]] = [list(self.HEADERS)]
        rows.extend([list(row) for row in self.TEMPLATE_ROWS])
        return self._build_xlsx(rows, sheet_name=self.SHEET_NAME)

    async def import_inventory(
        self,
        session: AsyncSession,
        wine_cellar_id: UUID,
        file_bytes: bytes,
    ) -> InventoryImportResult:
        try:
            sheet_name, rows = self._extract_sheet_rows(BytesIO(file_bytes))
        except (BadZipFile, ET.ParseError) as exc:
            raise InventoryExcelError("Invalid .xlsx workbook") from exc
        parsed_rows = self._parse_inventory_rows(rows)

        created = 0
        updated = 0
        async with session.begin():
            quotas = ResourceQuotaRepository(session)
            space = await quotas.lock_for_cellar(wine_cellar_id)
            before = await quotas.usage(space.id) if space.subscription_plan.value == "FREE" else None
            for parsed_row in parsed_rows:
                if parsed_row.item_id is None:
                    session.add(
                        WineInventoryItemORM(
                            wine_cellar_id=wine_cellar_id,
                            wine_name=parsed_row.wine_name,
                            wine_type=parsed_row.wine_type,
                            age_years=parsed_row.age_years,
                            quantity=parsed_row.quantity,
                        )
                    )
                    created += 1
                    continue

                existing = await session.scalar(
                    select(WineInventoryItemORM).where(
                        WineInventoryItemORM.id == parsed_row.item_id,
                        WineInventoryItemORM.wine_cellar_id == wine_cellar_id,
                    ).with_for_update()
                )
                if existing is None:
                    raise InventoryExcelError(
                        f"Row {parsed_row.row_number}: inventory item id {parsed_row.item_id} does not exist"
                    )
                if existing.wine_cellar_id != wine_cellar_id:
                    raise InventoryExcelError(
                        f"Row {parsed_row.row_number}: inventory item id {parsed_row.item_id} does not belong to this wine cellar"
                    )

                existing.wine_name = parsed_row.wine_name
                existing.wine_type = parsed_row.wine_type
                existing.age_years = parsed_row.age_years
                existing.quantity = parsed_row.quantity
                updated += 1

            await session.flush()
            if before is not None:
                validate_inventory_growth(space.subscription_plan.value, space.space_type.value, before, await quotas.usage(space.id))

        return InventoryImportResult(
            sheet_name=sheet_name,
            total_rows=len(parsed_rows),
            created=created,
            updated=updated,
        )

    def _parse_inventory_rows(self, rows: list[tuple[int, dict[str, Any]]]) -> list[_ParsedInventoryRow]:
        if not rows:
            return []

        _, header_row = rows[0]
        header_map = self._normalize_headers(header_row)
        self._validate_headers(header_map)

        parsed_rows: list[_ParsedInventoryRow] = []
        seen_ids: set[UUID] = set()
        for row_number, row in rows[1:]:
            if self._is_row_empty(row):
                continue

            try:
                item_id = self._parse_optional_uuid(
                    row.get(self._column_key_for_header(header_map, "id")),
                    row_number=row_number,
                )
                if item_id is not None and item_id in seen_ids:
                    raise InventoryExcelError(f"Row {row_number}: duplicated inventory item id {item_id} in file")
                if item_id is not None:
                    seen_ids.add(item_id)

                wine_name = self._parse_required_text(row.get(self._column_key_for_header(header_map, "wine_name")), "wine_name", row_number)
                raw_type = row.get(self._column_key_for_header(header_map, "wine_type"))
                wine_type = str(raw_type).strip() or None if raw_type is not None else None
                raw_age = row.get(self._column_key_for_header(header_map, "age_years"))
                age_years = self._parse_non_negative_int(raw_age, "age_years", row_number) if raw_age not in (None, "") else None
                quantity = self._parse_non_negative_int(row.get(self._column_key_for_header(header_map, "quantity")), "quantity", row_number)
            except InventoryExcelError:
                raise
            except Exception as exc:
                raise InventoryExcelError(f"Row {row_number}: {exc}") from exc

            parsed_rows.append(
                _ParsedInventoryRow(
                    row_number=row_number,
                    item_id=item_id,
                    wine_name=wine_name,
                    wine_type=wine_type,
                    age_years=age_years,
                    quantity=quantity,
                )
            )

        return parsed_rows

    def _extract_sheet_rows(self, workbook: BytesIO) -> tuple[str, list[tuple[int, dict[str, Any]]]]:
        with ZipFile(workbook, "r") as archive:
            workbook_xml = self._read_xml(archive, "xl/workbook.xml")
            workbook_rels_xml = self._read_xml(archive, "xl/_rels/workbook.xml.rels")
            shared_strings = self._read_shared_strings(archive)

            ns_main = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            ns_rel = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}

            workbook_root = ET.fromstring(workbook_xml)
            sheets = workbook_root.findall("main:sheets/main:sheet", ns_main)
            if not sheets:
                raise InventoryExcelError("The workbook does not contain any sheets")

            sheet_node = next((sheet for sheet in sheets if sheet.attrib.get("name") == self.SHEET_NAME), sheets[0])
            sheet_name = sheet_node.attrib.get("name", self.SHEET_NAME)
            relation_id = sheet_node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if not relation_id:
                raise InventoryExcelError("The workbook sheet does not have a valid relationship id")

            rels_root = ET.fromstring(workbook_rels_xml)
            rel = next((item for item in rels_root.findall("rel:Relationship", ns_rel) if item.attrib.get("Id") == relation_id), None)
            if rel is None:
                raise InventoryExcelError("The workbook sheet relationship could not be resolved")

            target = rel.attrib.get("Target")
            if not target:
                raise InventoryExcelError("The workbook sheet target is missing")

            sheet_path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
            sheet_xml = self._read_xml(archive, sheet_path)
            sheet_root = ET.fromstring(sheet_xml)
            rows = self._parse_sheet_rows(sheet_root, shared_strings)

        return sheet_name, rows

    def _parse_sheet_rows(self, sheet_root: ET.Element, shared_strings: list[str]) -> list[tuple[int, dict[str, Any]]]:
        ns_main = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheet_data = sheet_root.find("main:sheetData", ns_main)
        if sheet_data is None:
            return []

        rows: list[tuple[int, dict[str, Any]]] = []
        for row_node in sheet_data.findall("main:row", ns_main):
            row_number = int(row_node.attrib.get("r", "0") or "0")
            row_map: dict[str, Any] = {}
            for cell in row_node.findall("main:c", ns_main):
                ref = cell.attrib.get("r")
                if not ref:
                    continue
                row_map[self._column_key(ref)] = self._read_cell_value(cell, shared_strings)
            rows.append((row_number, row_map))
        return rows

    def _read_cell_value(self, cell: ET.Element, shared_strings: list[str]) -> Any:
        cell_type = cell.attrib.get("t")
        value_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
        if cell_type == "inlineStr":
            text_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
            if text_node is None:
                return ""
            return "".join(text_node.itertext())
        if cell_type == "s" and value_node is not None:
            index = int(value_node.text or "0")
            return shared_strings[index] if 0 <= index < len(shared_strings) else ""
        if value_node is None:
            return ""
        return value_node.text or ""

    def _read_shared_strings(self, archive: ZipFile) -> list[str]:
        try:
            shared_xml = archive.read("xl/sharedStrings.xml")
        except KeyError:
            return []

        ns_main = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        root = ET.fromstring(shared_xml)
        values: list[str] = []
        for node in root.findall("main:si", ns_main):
            values.append("".join(node.itertext()))
        return values

    def _normalize_headers(self, header_row: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        duplicates: set[str] = set()
        for cell_ref, raw_value in header_row.items():
            header = self._normalize_header_value(raw_value)
            if not header:
                continue
            if header in normalized.values():
                duplicates.add(header)
                continue
            normalized[cell_ref] = header
        if duplicates:
            raise InventoryExcelError(
                "The workbook contains duplicated headers",
                errors=[{"header": header} for header in sorted(duplicates)],
            )
        return normalized

    def _validate_headers(self, header_map: dict[str, str]) -> None:
        headers = set(header_map.values())
        missing = [header for header in self.REQUIRED_HEADERS if header not in headers]
        if missing:
            raise InventoryExcelError(
                "The workbook is missing required headers",
                errors=[{"missing_header": header} for header in missing],
            )

        allowed = set(self.HEADERS)
        unknown = sorted(headers - allowed)
        if unknown:
            raise InventoryExcelError(
                "The workbook contains unknown headers",
                errors=[{"unknown_header": header} for header in unknown],
            )

    def _column_key_for_header(self, header_map: dict[str, str], header_name: str) -> str | None:
        for column_key, normalized_header in header_map.items():
            if normalized_header == header_name:
                return column_key
        return None

    def _is_row_empty(self, row: dict[str, Any]) -> bool:
        return all(self._normalize_cell_value(value) == "" for value in row.values())

    def _parse_required_text(self, raw_value: Any, field_name: str, row_number: int) -> str:
        value = self._normalize_cell_value(raw_value)
        if not value:
            raise InventoryExcelError(f"Row {row_number}: {field_name} is required")
        if len(value) > 255:
            raise InventoryExcelError(f"Row {row_number}: {field_name} must not exceed 255 characters")
        return value

    def _parse_optional_uuid(self, raw_value: Any, *, row_number: int) -> UUID | None:
        value = self._normalize_cell_value(raw_value)
        if not value:
            return None
        try:
            return UUID(value)
        except ValueError as exc:
            raise InventoryExcelError(f"Row {row_number}: invalid inventory item id '{value}'") from exc

    def _parse_non_negative_int(self, raw_value: Any, field_name: str, row_number: int) -> int:
        value = self._normalize_cell_value(raw_value)
        if value == "":
            raise InventoryExcelError(f"Row {row_number}: {field_name} is required")
        try:
            if "." in value:
                parsed = float(value)
                if not parsed.is_integer():
                    raise ValueError
                int_value = int(parsed)
            else:
                int_value = int(value)
        except (TypeError, ValueError) as exc:
            raise InventoryExcelError(f"Row {row_number}: {field_name} must be a non-negative integer") from exc
        if int_value < 0:
            raise InventoryExcelError(f"Row {row_number}: {field_name} must be greater than or equal to zero")
        return int_value

    def _normalize_cell_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def _normalize_header_value(self, value: Any) -> str:
        return self._normalize_cell_value(value).lower()

    def _read_xml(self, archive: ZipFile, path: str) -> bytes:
        try:
            return archive.read(path)
        except KeyError as exc:
            raise InventoryExcelError(f"Missing required workbook part: {path}") from exc

    def _build_xlsx(self, rows: list[list[Any]], *, sheet_name: str) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._build_content_types_xml())
            archive.writestr("_rels/.rels", self._build_root_rels_xml())
            archive.writestr("xl/workbook.xml", self._build_workbook_xml(sheet_name))
            archive.writestr("xl/_rels/workbook.xml.rels", self._build_workbook_rels_xml())
            archive.writestr("xl/styles.xml", self._build_styles_xml())
            archive.writestr("xl/worksheets/sheet1.xml", self._build_sheet_xml(rows))
        buffer.seek(0)
        return buffer.getvalue()

    def _build_content_types_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>
"""

    def _build_root_rels_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""

    def _build_workbook_xml(self, sheet_name: str) -> str:
        safe_sheet_name = escape(sheet_name)
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{safe_sheet_name}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""

    def _build_workbook_rels_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""

    def _build_styles_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1">
    <font>
      <sz val="11"/>
      <color theme="1"/>
      <name val="Calibri"/>
      <family val="2"/>
    </font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border>
      <left/>
      <right/>
      <top/>
      <bottom/>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>
"""

    def _build_sheet_xml(self, rows: list[list[Any]]) -> str:
        max_row = len(rows)
        max_col = max((len(row) for row in rows), default=0)
        dimension = f"A1:{self._column_letter(max_col)}{max_row}" if max_row and max_col else "A1"

        sheet_rows = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for col_index, value in enumerate(row, start=1):
                cell_ref = f"{self._column_letter(col_index)}{row_index}"
                cells.append(self._build_cell_xml(cell_ref, value))
            sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

        sheet_data = "".join(sheet_rows)
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="{dimension}"/>
  <sheetViews>
    <sheetView workbookViewId="0"/>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <sheetData>{sheet_data}</sheetData>
</worksheet>
"""

    def _build_cell_xml(self, cell_ref: str, value: Any) -> str:
        if value is None:
            return f'<c r="{cell_ref}"/>'
        if isinstance(value, bool):
            return f'<c r="{cell_ref}" t="b"><v>{1 if value else 0}</v></c>'
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        text = escape(str(value))
        return f'<c r="{cell_ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    def _column_letter(self, index: int) -> str:
        if index < 1:
            raise ValueError("Column index must be greater than zero")
        letters = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            letters = chr(65 + remainder) + letters
        return letters

    def _column_key(self, cell_ref: str) -> str:
        letters = "".join(char for char in cell_ref if char.isalpha())
        if not letters:
            raise ValueError(f"Invalid cell reference: {cell_ref}")
        return letters
