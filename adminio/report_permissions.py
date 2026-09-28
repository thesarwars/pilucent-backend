"""Proxy model that exists only to anchor section-level permissions for Reports.

This model creates **no database table**. Its sole purpose is to let Django's
permission framework generate ``auth_permission`` rows (via ``makemigrations``)
that represent section-level actions on the "reports" area of the application.

These codenames are referenced by ``required_permissions`` on report views and
checked by ``HasCompanyPermission`` at runtime.
"""

from django.db import models


class ReportPermission(models.Model):
    """Virtual permission anchor for the Reports section."""

    class Meta:
        managed = False  # no DB table
        default_permissions = ()  # skip auto add/change/delete/view
        permissions = [
            ("view_reports", "Can view reports"),
            ("add_reports", "Can add reports"),
            ("change_reports", "Can edit reports"),
            ("delete_reports", "Can delete reports"),
        ]
