from pydantic import BaseModel
from typing import Optional

class CreateUserOut(BaseModel):
    status: bool
    message: Optional[str] = None
    client_id: Optional[int] = None

class ValidatePayResponse(BaseModel):
    success: bool
    message: str
    subscription_id: Optional[str] = None
    order_id: Optional[str] = None


class LoginSuccessResponse(BaseModel):
    success: bool = True
    message: str
    user: Optional[str] = None  # Puedes poner más campos como email, id, etc.
    access_token: Optional[str] = None  # Si usas JWT o sesión


class LoginErrorResponse(BaseModel):
    success: bool = False
    message: str