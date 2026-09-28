from django.urls import path
from weapi.django_rest.views.payroll.contact_info_setting import (
    PayrollContactInfoSettingCreateView,
    PayrollContactInfoSettingDetailUpdateView,
)

urlpatterns = [
    path(
        r"",
        PayrollContactInfoSettingCreateView.as_view(),
        name="payroll-contact-info-setting-create",
    ),
    path(
        r"/<uuid:uid>",
        PayrollContactInfoSettingDetailUpdateView.as_view(),
        name="payroll-contact-info-setting-detail-update",
    ),
]
