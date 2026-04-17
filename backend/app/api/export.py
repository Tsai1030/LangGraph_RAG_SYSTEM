import urllib.parse

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.export import ExportRequest
from app.services.export_service import generate_csv, generate_excel

router = APIRouter(prefix="/export", tags=["export"])


@router.post("/excel")
async def export_excel(
    body: ExportRequest,
    current_user: User = Depends(get_current_user),
):
    content = generate_excel(body.form_data, body.filename)
    safe_name = urllib.parse.quote(f"{body.filename}.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@router.post("/csv")
async def export_csv(
    body: ExportRequest,
    current_user: User = Depends(get_current_user),
):
    content = generate_csv(body.form_data)
    safe_name = urllib.parse.quote(f"{body.filename}.csv")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )
