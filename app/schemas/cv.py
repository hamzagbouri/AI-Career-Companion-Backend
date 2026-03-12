from pydantic import BaseModel


class CVResponse(BaseModel):

    id: int
    filename: str
    extracted_text: str

    class Config:
        from_attributes = True