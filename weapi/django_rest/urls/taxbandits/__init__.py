from django.urls import path, include

urlpatterns = [
    path(r"/business", include("weapi.django_rest.urls.taxbandits.business")),
    path(r"/form-940", include("weapi.django_rest.urls.taxbandits.form_940")),
    path(r"/form-941", include("weapi.django_rest.urls.taxbandits.form_941")),
    path(r"/form-8453emp", include("weapi.django_rest.urls.taxbandits.form_8453emp")),
    path(r"/webhooks", include("weapi.django_rest.urls.taxbandits.webhooks")),
]
