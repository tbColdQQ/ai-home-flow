from fastapi import Header, HTTPException

from app.services.auth_service import CurrentUser, get_user_by_token


def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="\u672a\u767b\u5f55")
    token = authorization.split(" ", 1)[1].strip()
    user = get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="\u767b\u5f55\u5df2\u5931\u6548")
    return user
