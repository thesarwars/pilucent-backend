from django.urls import re_path
from .django_rest.consumers.consumers_chat import ChatConsumer, RoomChatConsumer
from .django_rest.consumers.consumers_user_list import MessageUserListConsumer


websocket_urlpatterns = [
    re_path(r"^api/v1/chat/(?P<receiver_uid>[0-9a-f-]+)/$", ChatConsumer.as_asgi()),
    re_path(r"^api/v1/chat/room/(?P<room_uid>[0-9a-f-]+)/$", RoomChatConsumer.as_asgi()),
    re_path(r"^api/v1/chat/user-list/$", MessageUserListConsumer.as_asgi()),
]