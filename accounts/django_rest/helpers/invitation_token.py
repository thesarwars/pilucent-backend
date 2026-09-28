import base64
import json
from django.utils import timezone
from datetime import timedelta
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature


def generate_invitation_token(user_email):
    """
    Generate a signed token containing the user email with 48-hour expiration
    """
    signer = TimestampSigner()
    # Add timestamp for validation, but Django's TimestampSigner already includes one
    return signer.sign(user_email)


def verify_invitation_token(token):
    """
    Verify the token and extract user email
    Returns (is_valid, user_email, error_message)
    """
    signer = TimestampSigner()
    try:
        # Verify token with max_age of 48 hours (in seconds)
        user_email = signer.unsign(token, max_age=48 * 60 * 60)
        return True, user_email, None
    except SignatureExpired:
        return False, None, "Invitation link has expired"
    except BadSignature:
        return False, None, "Invalid invitation link"
    except Exception as e:
        return False, None, f"Error verifying invitation: {str(e)}"
