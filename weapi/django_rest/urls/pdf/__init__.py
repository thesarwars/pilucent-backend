from django.urls import path, include

urlpatterns = [
	path("/w4", include("weapi.django_rest.urls.pdf.w4")),
	path("/i9", include("weapi.django_rest.urls.pdf.i9")),
	path("/941", include("weapi.django_rest.urls.pdf.f941")),
	path("/940", include("weapi.django_rest.urls.pdf.f940")),
	path("/944", include("weapi.django_rest.urls.pdf.f944")),
]
