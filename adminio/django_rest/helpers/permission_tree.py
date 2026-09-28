from django.contrib.auth.models import Permission
from django.db.models import Q


# Codenames defined in adminio.report_permissions.ReportPermission
_REPORT_CODENAMES = {
    "view_reports": "view",
    "add_reports": "add",
    "change_reports": "edit",
    "delete_reports": "delete",
}


def get_report_permissions(company_user):
    """Return a dict like {"view": True, "add": False, ...} resolved from the DB.

    Checks both the user's direct permission overlay *and* their CompanyRole
    permissions so the result matches what HasCompanyPermission will enforce.
    """
    held_codenames = set(
        Permission.objects.filter(
            Q(companyuser=company_user)
            | Q(companyrole__company_users=company_user),
            codename__in=_REPORT_CODENAMES.keys(),
        )
        .values_list("codename", flat=True)
        .distinct()
    )
    return {
        action: codename in held_codenames
        for codename, action in _REPORT_CODENAMES.items()
    }


def build_permission_tree(permissions):
    """Group `permissions` into the standard `app_label > model > perms` shape.

    Report permissions (anchored to the `adminio.reportpermission` synthetic
    ContentType — see migration 0009) flow through this tree like any other
    model so the role-builder UI can render them with the same component as
    chartofaccount, employee, etc.
    """
    permission_dict = {}
    for permission in permissions:
        app_label = permission.content_type.app_label
        model_name = permission.content_type.model
        app_dict = permission_dict.setdefault(app_label, {"model": {}})
        model_dict = app_dict["model"].setdefault(model_name, [])
        model_dict.append({"id": permission.id, "codename": permission.codename})
    return {"app_label": permission_dict}

