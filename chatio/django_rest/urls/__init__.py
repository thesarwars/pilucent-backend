from django.urls import path, include

urlpatterns = [
    path("/rooms", include("chatio.django_rest.urls.chat_rooms")),
    path("/messages", include("chatio.django_rest.urls.messages")),
]
