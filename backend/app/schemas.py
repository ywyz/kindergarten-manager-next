from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import security


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str | None
    role: str
    is_active: bool
    version: int


class MeOut(BaseModel):
    account: AccountOut
    class_id: None = None
    assignment_status: str
    can_prepare: bool = False


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return security.normalize_username(v)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        security.validate_password(v)
        return v


class RegisterOut(BaseModel):
    account: AccountOut
    next_action: str = "login"


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return security.normalize_username(v)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        security.validate_password(v)
        return v


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    expected_version: int = Field(..., ge=1)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        return security.normalize_display_name(v)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str
    expected_version: int = Field(..., ge=1)

    @field_validator("current_password")
    @classmethod
    def validate_current_password(cls, v: str) -> str:
        security.validate_password(v)
        return v

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        security.validate_password(v)
        return v


class PasswordResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str
    expected_version: int = Field(..., ge=1)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        security.validate_password(v)
        return v


class TeacherListOut(BaseModel):
    items: list[AccountOut]
    total: int
    offset: int
    limit: int


class PasswordResetOut(BaseModel):
    account: AccountOut
    sessions_revoked: bool
