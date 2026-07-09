from pydantic import BaseModel


class WineInventoryImportResponse(BaseModel):
    sheet_name: str
    total_rows: int
    created: int
    updated: int

