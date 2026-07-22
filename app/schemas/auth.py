from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Any

class UserCreate(BaseModel):
    full_name: str = Field(..., example="Nahid Hasan")
    email: EmailStr = Field(..., example="nahidhasan@gmail.com")
    password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

    @model_validator(mode='after')
    def check_passwords_match(self) -> 'UserCreate':
        if self.password != self.confirm_password:
            raise ValueError("passwords do not match")
        return self

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class OTPVerify(BaseModel):
    email: EmailStr
    otp_code: str

class ForgotPassword(BaseModel):
    email: EmailStr

class ResetPassword(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str