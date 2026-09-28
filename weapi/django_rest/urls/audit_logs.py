from django.urls import path

from weapi.django_rest.views.audit_logs import PrivateWeAuditLogList

urlpatterns = [
    path(r"", PrivateWeAuditLogList.as_view(), name="weapi.auditlog-list"),
]
