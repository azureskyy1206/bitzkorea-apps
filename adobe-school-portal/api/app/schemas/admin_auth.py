from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AdminMeResponse(BaseModel):
    ok: bool = True
    role: str = "admin"
