"""Who is making the request: a session cookie for web pages, a bearer token for the API."""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import users

SESSION_COOKIE = "session"


class LoginRequired(Exception):
    """Raised by web pages when nobody is signed in; main.py turns it into a redirect to /login."""


class AdminRequired(Exception):
    """Raised by admin-only web pages; main.py turns it into a 403 page."""


def optional_user(request: Request):
    return users.user_for_token(request.cookies.get(SESSION_COOKIE))


def require_user(request: Request):
    user = optional_user(request)
    if user is None:
        raise LoginRequired()
    return user


def require_admin(user=Depends(require_user)):
    if user["role"] != "admin":
        raise AdminRequired()
    return user


bearer = HTTPBearer(auto_error=False, description="Token returned by POST /api/auth/login")


def api_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    return credentials.credentials if credentials else None


def api_user(token=Depends(api_token)):
    user = users.user_for_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return user


def api_admin(user=Depends(api_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
