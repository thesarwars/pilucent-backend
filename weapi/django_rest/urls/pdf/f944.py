from django.urls import path
from weapi.django_rest.views.pdf.f944 import DownloadForm944View, DebugPDF944FieldsView

urlpatterns = [
	path(
		r"/",
		DownloadForm944View.as_view(),
		name="weapi.pdf.944",
	),
	path(
        r"/debug-fields/",
        DebugPDF944FieldsView.as_view(),
        name="weapi.pdf.944.debug_fields",
    ),
]
