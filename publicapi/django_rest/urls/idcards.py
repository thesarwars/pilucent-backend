from django.urls import path

from ..views import idcards as v

urlpatterns = [
    path("/verify/<str:token>", v.PublicCardVerify.as_view(), name="publicapi.idcard-verify"),
]
media = [
    path("/<str:signed>", v.PublicCardMedia.as_view(), name="publicapi.idcard-media"),
]
