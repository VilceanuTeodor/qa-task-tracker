from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import api, audit, auth, db, monitoring, users, web, webhooks

# Before the app is created, so Sentry can hook into FastAPI and catch every crash.
monitoring.init_sentry()
# The app's own log lines (who did what): printed to stdout, so the terminal, Docker and Render show them.
audit.configure_logging()


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    generated = users.ensure_admin()
    if generated:
        username, password = generated
        print(
            "\n" + "=" * 60 +
            "\n Admin account created"
            f"\n   username: {username}"
            f"\n   password: {password}"
            "\n Save it now - it won't be shown again."
            "\n (Set ADMIN_PASSWORD before starting to choose your own.)"
            "\n" + "=" * 60 + "\n",
            flush=True,
        )
    webhooks.start_worker()   # sends queued webhook deliveries in the background
    yield
    webhooks.stop_worker()


app = FastAPI(title="Task Tracker", description="A basic Jira-like task tracker.", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
app.include_router(api.auth_router)
app.include_router(api.router)
app.include_router(api.admin_router)
app.include_router(web.router)


@app.exception_handler(auth.LoginRequired)
async def redirect_to_login(request: Request, exc):
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    # Only GET pages can be returned to after logging in.
    if request.method == "GET" and target != "/":
        return RedirectResponse(f"/login?{urlencode({'next': target})}", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(auth.AdminRequired)
async def admin_only(request: Request, exc):
    return web.render(
        request, "error.html", auth.optional_user(request), status_code=403,
        heading="Access denied", message="This page is only available to admins.",
    )
