from django.urls import path
from adminio.django_rest.views.admin_permissions import AdminUserPermissionsView, GroupPermissionsListView

urlpatterns = [
    # path("/user/<str:user_uid>", AdminUserPermissionsView.as_view(), name="POST.adminio.admin-user-permissions"),
    path("", GroupPermissionsListView.as_view(), name="POST.adminio.admin-user-permissions"),
]