# accounts/utils/tokens.py
import jwt
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

def decode_access_token(token):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def generate_access_token(user):
    payload = {
        "user_id": user.id,
        "email": user.email,
        "exp": timezone.now() + timedelta(minutes=15),
        "iat": timezone.now(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
