from django.urls import path
from weapi.django_rest.views.pdf.f941 import DownloadForm941View, DebugForm941PDFFieldsView, Form941SampleDataView

urlpatterns = [
	path(
		r"",
		DownloadForm941View.as_view(),
		name="weapi.pdf.f941",
	),
	path(
        r"/debug-fields/",
        DebugForm941PDFFieldsView.as_view(),
        name="weapi.pdf.f941.debug_fields",
    ),
    path(
        r"/sample-data/",
        Form941SampleDataView.as_view(),
        name="weapi.pdf.f941.sample_data",
    ),
]