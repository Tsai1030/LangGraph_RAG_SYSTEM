from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.export import ExportRequest

router = APIRouter(prefix="/export", tags=["export"])


@router.post("/excel")
async def export_excel(
    body: ExportRequest,
    current_user: User = Depends(get_current_user),
):
    # Phase 4 will implement openpyxl generation
    return Response(content=b"", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/csv")
async def export_csv(
    body: ExportRequest,
    current_user: User = Depends(get_current_user),
):
    # Phase 4 will implement CSV generation
    return Response(
        content="\ufeff",  # BOM for Excel Chinese compatibility
        media_type="text/csv; charset=utf-8-sig",
    )
