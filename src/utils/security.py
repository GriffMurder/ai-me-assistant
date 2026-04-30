import hmac
import os

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


async def verify_owner(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
):
    """Require the correct APP_PASSWORD bearer token."""
    expected = os.getenv("APP_PASSWORD")
    if not expected:
        raise HTTPException(status_code=503, detail="Auth not configured (APP_PASSWORD unset)")
    if not credentials or not hmac.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def verify_twilio(request: Request):
    """Validate that the incoming request genuinely came from Twilio.

    Reconstructs the public URL from X-Forwarded-* headers because Render
    sits behind a proxy and request.url reflects internal scheme/host —
    Twilio's signature validator would silently fail without this correction.
    """
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not auth_token:
        raise HTTPException(status_code=503, detail="Twilio auth not configured")

    try:
        from twilio.request_validator import RequestValidator
    except ImportError:
        raise HTTPException(status_code=503, detail="Twilio library not installed")

    # Reconstruct the public-facing URL (what Twilio actually called)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.hostname))
    public_url = f"{proto}://{host}{request.url.path}"

    twilio_signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    params = dict(form)

    validator = RequestValidator(auth_token)
    if not validator.validate(public_url, params, twilio_signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
