import os

from dotenv import load_dotenv

load_dotenv()


def send_sms(to: str, body: str) -> str | None:
    """Send an SMS from Wesley's Twilio number. Returns the message SID or None on failure."""
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
        print(f"SMS failed: {e}")
        return None
