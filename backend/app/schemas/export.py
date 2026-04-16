from pydantic import BaseModel


class ExportRequest(BaseModel):
    form_data: dict
    filename: str = "export"
