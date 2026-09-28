from django.urls import path, include

urlpatterns = [
    path("", include("meapi.django_rest.urls.profiles")),
    path("/daily-time-trackings", include("meapi.django_rest.urls.time_trackings")),
    path("/shifts", include("meapi.django_rest.urls.shifts")),
    path("/notifications", include("meapi.django_rest.urls.notifications")),
]
