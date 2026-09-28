from django.urls import path

from accounts.django_rest.views.workspace import (
    JoinByCodeView,
    PinCompanyView,
    SelectCompanyView,
    WorkspaceMembershipsView,
)


urlpatterns = [
    path(r"/memberships", WorkspaceMembershipsView.as_view(), name="workspace_memberships"),
    path(r"/select-company", SelectCompanyView.as_view(), name="workspace_select_company"),
    # Switching company is the same exchange as the initial selection.
    path(r"/switch-company", SelectCompanyView.as_view(), name="workspace_switch_company"),
    path(r"/pin-company", PinCompanyView.as_view(), name="workspace_pin_company"),
    path(r"/join-by-code", JoinByCodeView.as_view(), name="workspace_join_by_code"),
]
