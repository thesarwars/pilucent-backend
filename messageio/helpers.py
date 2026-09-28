import logging

from firebase_admin import db

logger = logging.getLogger(__name__)


def send_message_to_firebase_database(instance):
    logger.info("Sending messages to firebase database...")
    user = instance.user
    if user:
        url = f"/messages/{user.slug}/"
    ref = db.reference(url)
    ref.push(
        {
            "timestamp": {".sv": "timestamp"},
        }
    )