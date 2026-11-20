from io import BytesIO
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.dependencies import (
    get_current_user_id,
    get_device_assignment_repository,
    get_space_repository,
    get_wine_cellar_repository,
    get_wine_inventory_repository,
    get_inventory_stock_service,
    get_stock_movement_repository,
)
from app.wine_cellar.applications.inventory_stock_service import InventoryItemNotFoundError, InsufficientStockError
from ..resources.stock_movement_resource import StockExitRequest, StockMovementResponse
from ..resources.request_models import CreateWineCellarInSpaceRequest
from ..resources.wine_inventory_request import CreateWineItemInCellarRequest
from app.core.database import AsyncSessionLocal
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.wine_cellar.applications import InventoryExcelError, WineInventoryExcelService
from app.wine_cellar.applications.inventory_excel_service import XLSX_MIME_TYPE
from app.wine_cellar.domain.models import WineCellar
from ..resources import (
    CreateWineCellarRequest,
    CreateWineInventoryItemRequest,
    LinkWineCellarDeviceRequest,
    WineInventoryImportResponse,
    UpdateWineInventoryItemRequest,
    UpdateWineCellarRequest,
    WineCellarResponse,
    WineInventoryItemResponse,
)


router = APIRouter(prefix="/api/v1", tags=["Wine Cellars"])


async def _get_space_for_user(space_id: UUID, user_id: int, space_repo):
    space = await space_repo.find_by_id(space_id)
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found")
    # Space membership/role is enforced by the shared router guard.
    return space


async def _get_wine_cellar_for_user(wine_cellar_id: UUID, user_id: int, wine_cellar_repo, space_repo):
    wine_cellar = await wine_cellar_repo.find_by_id(wine_cellar_id)
    if not wine_cellar:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wine cellar not found")
    await _get_space_for_user(wine_cellar.space_id, user_id, space_repo)
    return wine_cellar


async def _get_wine_inventory_item_for_user(wine_cellar_id: UUID, inventory_item_id: UUID, user_id: int, wine_cellar_repo, space_repo, inventory_repo, *, for_update: bool = False):
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    inventory_item = await inventory_repo.find_by_id(inventory_item_id, for_update=for_update, wine_cellar_id=wine_cellar_id)
    if not inventory_item or inventory_item.wine_cellar_id != wine_cellar.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wine inventory item not found")
    return wine_cellar, inventory_item


@router.get("/wine-cellars")
async def list_user_wine_cellars(
    space_id: UUID | None = None,
    space_id_camel: UUID | None = Query(default=None, alias="spaceId"),
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
) -> List[WineCellarResponse]:
    if space_id is not None and space_id_camel is not None and space_id != space_id_camel:
        raise HTTPException(status_code=422, detail="Conflicting space_id and spaceId")
    selected_space_id = space_id if space_id is not None else space_id_camel
    if selected_space_id is not None:
        await _get_space_for_user(selected_space_id, user_id, space_repo)
    wine_cellars = await wine_cellar_repo.find_all_by_owner_user_id(user_id, selected_space_id)
    return [WineCellarResponse.from_domain(cellar) for cellar in wine_cellars]


@router.get("/spaces/{space_id}/wine-cellars")
async def list_wine_cellars(
    space_id: UUID,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
) -> List[WineCellarResponse]:
    await _get_space_for_user(space_id, user_id, space_repo)
    wine_cellars = await wine_cellar_repo.find_all_by_space_id(space_id)
    return [WineCellarResponse.from_domain(wine_cellar) for wine_cellar in wine_cellars]


@router.post("/spaces/{space_id}/wine-cellars", status_code=status.HTTP_201_CREATED)
async def create_wine_cellar(
    space_id: UUID,
    request: CreateWineCellarRequest,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
) -> WineCellarResponse:
    await _get_space_for_user(space_id, user_id, space_repo)

    wine_cellar = WineCellar(
        space_id=space_id,
        name=request.name,
        description=request.description,
    )
    saved = await wine_cellar_repo.save(wine_cellar)
    return WineCellarResponse.from_domain(saved)


@router.post("/wine-cellars", status_code=status.HTTP_201_CREATED)
async def create_wine_cellar_direct(
    request: CreateWineCellarInSpaceRequest,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
) -> WineCellarResponse:
    return await create_wine_cellar(request.space_id, request, user_id, space_repo, wine_cellar_repo)


@router.put("/wine-cellars/{wine_cellar_id}")
async def update_wine_cellar(
    wine_cellar_id: UUID,
    request: UpdateWineCellarRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
) -> WineCellarResponse:
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    wine_cellar.update(name=request.name, description=request.description)
    saved = await wine_cellar_repo.save(wine_cellar)
    return WineCellarResponse.from_domain(saved)


@router.delete("/wine-cellars/{wine_cellar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wine_cellar(
    wine_cellar_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
):
    await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    await wine_cellar_repo.delete(wine_cellar_id)


@router.post("/wine-cellars/{wine_cellar_id}/devices")
async def link_device_to_wine_cellar(
    wine_cellar_id: UUID,
    request: LinkWineCellarDeviceRequest,
    http_request: Request,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    assignment_repo = Depends(get_device_assignment_repository),
) -> WineCellarResponse:
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)

    device_assignment = await assignment_repo.find_by_device_id(request.device_id)
    if not device_assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if device_assignment.space_id != wine_cellar.space_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device does not belong to the same space as the wine cellar")
    if wine_cellar.device_id is not None and wine_cellar.device_id != request.device_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Wine cellar already has a linked device")

    existing = await wine_cellar_repo.find_by_device_id(request.device_id)
    if existing and existing.id != wine_cellar.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is already linked to another wine cellar")

    wine_cellar.link_device(request.device_id)
    saved = await wine_cellar_repo.save(wine_cellar)

    device_event_publisher = getattr(http_request.app.state, "device_event_publisher", None)
    if device_event_publisher is not None:
        await device_event_publisher.publish_assignment_changed(device_assignment)

    return WineCellarResponse.from_domain(saved)


@router.delete("/wine-cellars/{wine_cellar_id}/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_device_from_wine_cellar(
    wine_cellar_id: UUID,
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
):
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    if wine_cellar.device_id != device_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device is not linked to this wine cellar")

    wine_cellar.unlink_device()
    await wine_cellar_repo.save(wine_cellar)


@router.get("/wine-cellars/{wine_cellar_id}/inventory")
async def list_wine_inventory(
    wine_cellar_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    inventory_repo = Depends(get_wine_inventory_repository),
) -> List[WineInventoryItemResponse]:
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    items = await inventory_repo.find_all_by_wine_cellar_id(wine_cellar.id)
    return [WineInventoryItemResponse.from_domain(item) for item in items]


@router.get("/wine-cellars/{wine_cellar_id}/inventory/export", summary="Export wine cellar inventory to Excel")
async def export_wine_inventory(
    wine_cellar_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    db: AsyncSession = Depends(get_db),
):
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)

    workbook_bytes = await WineInventoryExcelService().export_inventory(db, wine_cellar.id)

    filename = f"wine-cellar-{wine_cellar.id}-inventory.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        BytesIO(workbook_bytes),
        media_type=XLSX_MIME_TYPE,
        headers=headers,
    )


@router.get("/wine-cellars/{wine_cellar_id}/inventory/template", summary="Download inventory import template")
async def download_wine_inventory_template(
    wine_cellar_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
):
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)

    workbook_bytes = WineInventoryExcelService().export_template()
    filename = f"wine-cellar-{wine_cellar.id}-inventory-template.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        BytesIO(workbook_bytes),
        media_type=XLSX_MIME_TYPE,
        headers=headers,
    )


@router.post("/wine-cellars/{wine_cellar_id}/inventory/import", summary="Import wine cellar inventory from Excel")
async def import_wine_inventory(
    wine_cellar_id: UUID,
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
) -> WineInventoryImportResponse:
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)

    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file must be an .xlsx workbook")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is empty")

    try:
        async with AsyncSessionLocal() as session:
            result = await WineInventoryExcelService().import_inventory(session, wine_cellar.id, file_bytes)
    except InventoryExcelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": exc.message,
                "errors": exc.errors,
            },
        ) from exc

    return WineInventoryImportResponse(
        sheet_name=result.sheet_name,
        total_rows=result.total_rows,
        created=result.created,
        updated=result.updated,
    )


@router.post("/wine-cellars/{wine_cellar_id}/inventory", status_code=status.HTTP_201_CREATED)
async def create_wine_inventory_item(
    wine_cellar_id: UUID,
    request: CreateWineInventoryItemRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    inventory_repo = Depends(get_wine_inventory_repository),
) -> WineInventoryItemResponse:
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    from app.wine_cellar.domain.models import WineInventoryItem

    inventory_item = WineInventoryItem(
        wine_cellar_id=wine_cellar.id,
        **request.model_dump(),
    )
    saved = await inventory_repo.save(inventory_item)
    return WineInventoryItemResponse.from_domain(saved)


@router.post("/wine-items", status_code=status.HTTP_201_CREATED)
async def create_wine_item_direct(
    request: CreateWineItemInCellarRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    inventory_repo = Depends(get_wine_inventory_repository),
) -> WineInventoryItemResponse:
    body = CreateWineInventoryItemRequest.model_validate(request.model_dump(exclude={"wine_cellar_id"}))
    return await create_wine_inventory_item(request.wine_cellar_id, body, user_id, wine_cellar_repo, space_repo, inventory_repo)


@router.put("/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}")
@router.patch("/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}")
async def update_wine_inventory_item(
    wine_cellar_id: UUID,
    inventory_item_id: UUID,
    request: UpdateWineInventoryItemRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    inventory_repo = Depends(get_wine_inventory_repository),
) -> WineInventoryItemResponse:
    _, inventory_item = await _get_wine_inventory_item_for_user(
        wine_cellar_id, inventory_item_id, user_id, wine_cellar_repo, space_repo, inventory_repo, for_update=True,
    )
    inventory_item = inventory_item.with_changes(request.model_dump(exclude_unset=True))
    saved = await inventory_repo.save(inventory_item)
    return WineInventoryItemResponse.from_domain(saved)


@router.delete("/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wine_inventory_item(
    wine_cellar_id: UUID,
    inventory_item_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    inventory_repo = Depends(get_wine_inventory_repository),
):
    await _get_wine_inventory_item_for_user(
        wine_cellar_id, inventory_item_id, user_id, wine_cellar_repo, space_repo, inventory_repo
    )
    await inventory_repo.delete(inventory_item_id)


@router.post("/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}/movements", status_code=201)
async def record_stock_exit(
    wine_cellar_id: UUID,
    inventory_item_id: UUID,
    request: StockExitRequest,
    user_id: int = Depends(get_current_user_id),
    service = Depends(get_inventory_stock_service),
) -> StockMovementResponse:
    try:
        movement = await service.withdraw(
            wine_cellar_id, inventory_item_id, user_id, request.quantity, request.reason, request.notes,
        )
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StockMovementResponse.model_validate(movement.model_dump())


@router.get("/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}/movements")
async def list_stock_movements(
    wine_cellar_id: UUID,
    inventory_item_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    inventory_repo = Depends(get_wine_inventory_repository),
    movement_repo = Depends(get_stock_movement_repository),
) -> list[StockMovementResponse]:
    await _get_wine_inventory_item_for_user(
        wine_cellar_id, inventory_item_id, user_id, wine_cellar_repo, space_repo, inventory_repo,
    )
    return [StockMovementResponse.model_validate(movement.model_dump()) for movement in await movement_repo.list_for_item(
        wine_cellar_id, inventory_item_id, limit,
    )]
