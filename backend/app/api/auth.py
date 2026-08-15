from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.api.deps import current_user
from app.services.auth_service import (
    CurrentUser,
    authenticate,
    create_session,
    change_password,
    revoke_session,
    user_to_dict,
)


router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
def login(body: LoginRequest) -> dict:
    user = authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="\u8d26\u53f7\u6216\u5bc6\u7801\u9519\u8bef")
    token = create_session(user.id)
    return user_to_dict(user, token)


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)) -> dict:
    return user_to_dict(user)


@router.post("/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if authorization and authorization.lower().startswith("bearer "):
        revoke_session(authorization.split(" ", 1)[1].strip())
    return {"message": "logged out"}


@router.post("/change-password")
def update_password(body: ChangePasswordRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if not change_password(user.id, body.old_password, body.new_password):
        raise HTTPException(status_code=400, detail="原密码不正确")
    return {"message": "updated"}
