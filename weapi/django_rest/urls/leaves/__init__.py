from django.urls import path, include

urlpatterns = [
	path("/type", include("weapi.django_rest.urls.leaves.leave_type")),
	path("/request", include("weapi.django_rest.urls.leaves.leave_request")),
 	path("/balance", include("weapi.django_rest.urls.leaves.leave_balance")),
	path("/encashment", include("weapi.django_rest.urls.leaves.leave_encashment")),
]
