import hashlib, random, time, logging

logger = logging.getLogger(__name__)


def get_otp():
    # Generate a unique string combining current time and some randomness
    unique_string = str(time.time()) + str(random.randint(0, 999999))
    # Hash the unique string using SHA-256
    hashed_string = hashlib.sha256(unique_string.encode()).hexdigest()
    # Convert the hashed string into a numerical representation
    numeric_representation = int(hashed_string, 16)
    return str(numeric_representation)[:6]  # Extract the first 6 digits as OTP
