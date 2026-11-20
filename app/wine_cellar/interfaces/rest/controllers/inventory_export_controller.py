import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.wine_cellar.applications.inventory_excel_service import XLSX_MIME_TYPE
from app.wine_cellar.applications.inventory_export_service import InventoryExportNotFoundError, InventoryExportService, InventoryExportTooLargeError
from app.wine_cellar.infrastructure.reporting.inventory_report_renderer import filename, render_pdf, render_xlsx


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory exports"])


@router.get("/export", response_class=Response, responses={200: {"content": {
    XLSX_MIME_TYPE: {"schema": {"type": "string", "format": "binary"}},
    "application/pdf": {"schema": {"type": "string", "format": "binary"}},
}}})
async def export_inventory(
    space_id: UUID,
    cellar_id: UUID | None = None,
    format: Literal["xlsx", "pdf"] = "xlsx",
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await InventoryExportService(db).load(space_id, cellar_id)
    except InventoryExportNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except InventoryExportTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    try:
        content = await run_in_threadpool(render_xlsx if format == "xlsx" else render_pdf, data)
    except Exception as exc:
        logger.warning("Inventory report generation failed (format %s)", format)
        raise HTTPException(500, "Could not generate inventory report") from exc
    return Response(content, media_type=XLSX_MIME_TYPE if format == "xlsx" else "application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename(data, format)}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })
