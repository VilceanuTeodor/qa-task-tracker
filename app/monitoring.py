"""Error monitoring with Sentry.

Sentry is switched on only when SENTRY_DSN is set (on Render). Locally and in the
tests it stays off, so nothing is sent unless you ask for it.
"""
import os

import sentry_sdk


def init_sentry():
    """Start Sentry if SENTRY_DSN is set. Returns True if it was started."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    sentry_sdk.init(
        dsn=dsn,
        # Lets you filter issues by where they happened. Render sets RENDER=true.
        environment=os.environ.get("SENTRY_ENVIRONMENT") or ("production" if os.environ.get("RENDER") else "development"),
        # Which version of the code raised the error: Render provides the deployed git commit.
        release=os.environ.get("SENTRY_RELEASE") or os.environ.get("RENDER_GIT_COMMIT") or None,
        # Performance tracing is off by default to stay well inside the free tier.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
        # Privacy: send stack traces and the code around each line, but not who the user is,
        # their cookies (the session token) or request bodies (the login body has the password).
        # Header values with names like "authorization" or "token" are filtered by default.
        # Local variables are off too: framework functions keep the raw request (including the
        # Authorization header) in variables such as `scope`, which name-based filtering misses.
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_bodies": [],
            "stack_frame_variables": False,
        },
    )
    return True
