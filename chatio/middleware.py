from urllib.parse import parse_qs
from django.contrib.auth.models import AnonymousUser
from django.conf import settings

from jwt import decode as jwt_decode

from channels.middleware import BaseMiddleware

from asgiref.sync import sync_to_async

from accounts.models import User


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        token = parse_qs(query_string).get("token", [None])[0]
        scope["user"] = AnonymousUser()

        if token:
            try:
                decoded = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])
                user = await sync_to_async(User.objects.get)(id=decoded["user_id"])
                scope["user"] = user
            except Exception:
                pass

        return await super().__call__(scope, receive, send)