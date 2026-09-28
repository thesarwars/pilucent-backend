from django.urls import path
from weapi.django_rest.views.pdf.i9 import DownloadFormI9View, DebugI9PDFFieldsView

urlpatterns = [
	path(
		r"/",
		DownloadFormI9View.as_view(),
		name="weapi.pdf.i9",
	),
	path(
        r"/debug-fields/",
        DebugI9PDFFieldsView.as_view(),
        name="weapi.pdf.i9.debug_fields",
    ),
]
