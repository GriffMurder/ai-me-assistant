import os

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()


def send_sms(to: str, body: str) -> str:
    """Send an SMS from Wesley's Twilio number. Returns the message SID."""
    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN"),
    )
    message = client.messages.create(
        from_=os.getenv("TWILIO_PHONE_NUMBER"),
        to=to,
        body=body,
    )
    return message.sid
