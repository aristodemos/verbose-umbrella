from pydantic import BaseModel, Field


class BBox(BaseModel):
    x0: float = Field(..., description="The x-coordinate of the bottom-left corner of the bounding box.")
    y0: float = Field(..., description="The y-coordinate of the bottom-left corner of the bounding box.")
    x1: float = Field(..., description="The x-coordinate of the top-right corner of the bounding box.")
    y1: float = Field(..., description="The y-coordinate of the top-right corner of the bounding box.")

    class Config:
        schema_extra = {
            "example": {
                "x0": 100.0,
                "y0": 200.0,
                "x1": 300.0,
                "y1": 400.0
            }
        }

class Evidence(BaseModel):
    page: int
    bbox: BBox | None = None
    method: str
    parser: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score of the extraction method, if applicable.")
    