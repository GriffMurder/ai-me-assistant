import os

from dotenv import load_dotenv

load_dotenv()

_REQUIRED = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER")


def _twilio_configured() -> tuple[bool, str]:
    """Return (True, "") if all required Twilio env vars are set, else (False, reason)."""
    missing = [k for k in _REQUIRED if not os.getenv(k)]
    if missing:
        return False, f"Missing Twilio env vars: {', '.join(missing)}"
    return True, ""


def send_sms(to: str, body: str) -> str | None:
    """Send an SMS from Wesley's Twilio number.

    Returns the message SID on success.
    Returns None and logs a structured error on failure (missing config or API error).
    Never raises — callers should check the return value or watch logs.
    """
    ok, reason = _twilio_configured()
    if not ok:
        print(f"❌ SMS not sent to {to}: {reason}")
        return None

    if not to:
        print("❌ SMS not sent: recipient 'to' is empty")
        return None

    try:
        from twilio.rest import Client
        client = Client(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN"),
        )
        message = client.messages.create(
            from_=os.getenv("TWILIO_PHONE_NUMBER"),
            to=to,
            body=body[:1600],
        )
        return message.sid
    except Exception as e:
        print(f"❌ SMS delivery failed to {to}: {type(e).__name__}: {e}")
        return None
