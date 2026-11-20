from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
import unicodedata
from xml.sax.saxutils import escape

from app.wine_cellar.applications.inventory_excel_service import WineInventoryExcelService
from app.wine_cellar.domain.models.inventory_export import InventoryExportData


def clean_text(value) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))


def filename(data: InventoryExportData, extension: str) -> str:
    def slug(text):
        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()[:50] or "inventario"
    scope = slug(data.cellar_name) if data.cellar_name else "todas-las-cavas"
    return f"vinevault-{slug(data.space_name)}-{scope}-{data.space_id.hex[:8]}-{data.generated_at:%Y%m%d}.{extension}"


def _columns(purpose: str) -> list[tuple[str, str]]:
    columns = [("cellar_name", "Cava"), ("wine_name", "Nombre del vino"), ("winery", "Bodega"),
               ("vintage", "Añada"), ("quantity", "Cantidad"), ("physical_location", "Ubicación física"),
               ("country", "País"), ("region", "Región"), ("appellation", "D.O. / Apelación"),
               ("wine_type", "Tipo / Cepa"), ("bottle_format", "Formato"), ("aging", "Crianza"),
               ("alcohol_percentage", "Alcohol (%)"), ("consumption_window", "Ventana de consumo")]
    if purpose == "BUSINESS":
        columns += [("purchase_price", "Costo unitario"), ("sale_price", "Precio de venta"),
                    ("min_stock_alert", "Stock mínimo"), ("supplier_name", "Proveedor"), ("batch_invoice_number", "Lote / Factura")]
    else:
        columns += [("purchase_price", "Precio pagado"), ("origin_type", "Origen de compra"), ("purchase_date", "Fecha de compra")]
    return columns + [("tasting_notes", "Notas de cata"), ("occasion_notes", "Notas previas"),
                      ("company_notes", "Notas internas"), ("would_buy_again", "¿Volvería a comprar?")]


def render_xlsx(data: InventoryExportData) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = "Inventario"
    columns = _columns(data.purpose)

    def write(target, row, values):
        for index, value in enumerate(values, 1):
            if hasattr(value, "value"):
                value = value.value
            if isinstance(value, str):
                value = clean_text(value)
            cell = target.cell(row, index, value)
            if isinstance(value, str):
                cell.data_type = "s"  # Never interpret user strings as formulas.
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    metadata = [
        ["VineVault — Inventario"], ["Espacio", data.space_name],
        ["Cava", data.cellar_name or "Todas las cavas"], ["Propósito", data.purpose],
        ["Generado (UTC)", data.generated_at.strftime("%Y-%m-%d %H:%M:%S")],
        ["Registros", len(data.items), "Botellas / unidades", data.quantity],
        ["Importación", "Editar la hoja inventory para reimportar en esta misma cava." if data.cellar_id else "Informe de espacio: para importar, descarga la plantilla de la cava destino."],
    ]
    for row, values in enumerate(metadata, 1):
        write(sheet, row, values)
    for row in (2, 3, 4, 5, 7):
        sheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
        sheet.row_dimensions[row].height = 30
    sheet["A1"].font = Font(size=16, bold=True, color="6A2338")
    write(sheet, 8, [label for _, label in columns])
    sheet.row_dimensions[8].height = 32
    for cell in sheet[8]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="6A2338")
    for number, item in enumerate(data.items, 9):
        write(sheet, number, [item.get(key) for key, _ in columns])
        sheet.row_dimensions[number].height = 45
        for index, (key, _) in enumerate(columns, 1):
            if key in {"purchase_price", "sale_price", "alcohol_percentage"}:
                sheet.cell(number, index).number_format = "0.00"
            elif key == "purchase_date":
                sheet.cell(number, index).number_format = "yyyy-mm-dd"
    if not data.items:
        write(sheet, 9, ["Sin ítems de inventario en este ámbito."])
    for index, (key, _) in enumerate(columns, 1):
        sheet.column_dimensions[get_column_letter(index)].width = 35 if "notes" in key else 28 if key in {"wine_name", "winery", "physical_location"} else 20
    sheet.freeze_panes = "C9"
    sheet.auto_filter.ref = f"A8:{get_column_letter(len(columns))}{max(8, 8 + len(data.items))}"
    sheet.print_title_rows = "1:8"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    # Import selects this sheet and expects machine-readable headers on row one.
    if data.cellar_id is not None:
        compatible = book.create_sheet(WineInventoryExcelService.SHEET_NAME)
        write(compatible, 1, WineInventoryExcelService.HEADERS)
        for number, item in enumerate(data.items, 2):
            write(compatible, number, [str(item["id"]), item["wine_name"], item.get("wine_type"), item.get("age_years"), item["quantity"]])
        compatible.freeze_panes = "A2"
        for letter in ("A", "B", "C", "D", "E"):
            compatible.column_dimensions[letter].width = 38 if letter in {"A", "B"} else 20
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


@lru_cache(maxsize=1)
def _pdf_font() -> str:
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    pdfmetrics.registerFont(TTFont("VineVaultVera", str(path)))
    return "VineVaultVera"


def render_pdf(data: InventoryExportData) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    font = _pdf_font()
    stream = BytesIO()
    page = landscape(A4)
    document = SimpleDocTemplate(stream, pagesize=page, leftMargin=20, rightMargin=20, topMargin=25, bottomMargin=30,
                                 title="VineVault - Inventario", author="VineVault", pageCompression=1)
    normal = ParagraphStyle("report", fontName=font, fontSize=8, leading=11, splitLongWords=True)
    small = ParagraphStyle("cell", parent=normal, fontSize=7, leading=9)
    heading = ParagraphStyle("heading", parent=normal, fontSize=15, leading=19, textColor=colors.HexColor("#6A2338"))

    def paragraph(value, style=small):
        text = "—" if value is None else clean_text(value)
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    content = [paragraph("VineVault — Reporte de inventario", heading), Spacer(1, 8),
               paragraph(f"Espacio: {data.space_name} | Cava: {data.cellar_name or 'Todas las cavas'}", normal),
               paragraph(f"Propósito: {data.purpose} | Generado: {data.generated_at:%Y-%m-%d %H:%M:%S} UTC", normal),
               paragraph(f"Registros: {len(data.items)} | Botellas / unidades: {data.quantity}", normal),
               paragraph("Precios unitarios registrados, sin moneda inferida. — indica un dato no informado.", normal), Spacer(1, 10)]
    if not data.items:
        content.append(paragraph("Sin ítems de inventario en este ámbito.", normal))
    else:
        headers = ("Cava", "Nombre del vino", "Bodega", "Añada", "Cant.", "Tipo / Cepa", "Costo / Venta" if data.purpose == "BUSINESS" else "Compra", "Ventana")
        rows = [[paragraph(label) for label in headers]]
        for item in data.items:
            purchase, sale = item.get("purchase_price"), item.get("sale_price")
            price = f"{purchase if purchase is not None else '—'} / {sale if sale is not None else '—'}" if data.purpose == "BUSINESS" else purchase
            rows.append([paragraph(value) for value in (item["cellar_name"], item["wine_name"], item.get("winery"), item.get("vintage"), item["quantity"], item.get("wine_type"), price, item.get("consumption_window"))])
        weights = (85, 150, 100, 40, 35, 100, 80, 112)
        widths = [weight * document.width / sum(weights) for weight in weights]
        table = LongTable(rows, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDE1E5")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5D5D5")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        content.append(table)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.drawString(20, 13, "VineVault | Inventario")
        canvas.drawRightString(page[0] - 20, 13, f"Página {doc.page}")
        canvas.restoreState()

    document.build(content, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
