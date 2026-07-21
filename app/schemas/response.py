from typing import Any, Optional
from pydantic import BaseModel

class StandardResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[Any] = None

    class Config:
        orm_mode = True
