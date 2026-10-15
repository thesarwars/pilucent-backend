"""Who may see and change a salary (salary profile §7).

Three role permissions (on `SalaryAudit`): view the figures, write a
structure, approve one. The active company's admin holds all three; anyone
else needs them through one of their roles *in this company* or their
per-company overlay. Django's global user groups are not consulted: a user in
one company's admin group must not see another company's salaries.

Masking is the server's job. A caller without `view_salary_figures` is sent
no amounts at all -- not amounts with a flag the client is trusted to honour.
"""

from django.db.models import Q

VIEW_FIGURES = "view_salary_figures"
WRITE = "write_salary"
APPROVE = "approve_salary"
APP_LABEL = "employeeio"


def is_company_admin(user, company):
    from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME
    from companyio.models import CompanyUser

    return CompanyUser.objects.filter(
        user=user, company=company, roles__company=company, roles__name=ADMIN_GROUP_NAME, roles__is_system=True,
    ).exists()


def has_salary_permission(user, company, codename):
    from companyio.models import CompanyUser

    if not (user and user.is_authenticated) or company is None:
        return False
    if user.is_superuser or is_company_admin(user, company):
        return True
    held = (Q(roles__permission__codename=codename, roles__permission__content_type__app_label=APP_LABEL)
            | Q(permission__codename=codename, permission__content_type__app_label=APP_LABEL))
    return CompanyUser.objects.filter(user=user, company=company).filter(held).exists()


def can_view_figures(user, company):
    return has_salary_permission(user, company, VIEW_FIGURES)


def can_write(user, company):
    return has_salary_permission(user, company, WRITE)


def actor_role(user, company):
    """How the actor was entitled, as the audit records it."""
    from companyio.models import CompanyUser

    if user is None:
        return "system"
    if user.is_superuser:
        return "superuser"
    if is_company_admin(user, company):
        return "company admin"
    names = (CompanyUser.objects.filter(user=user, company=company)
             .values_list("roles__name", flat=True).distinct())
    return ", ".join(sorted(n for n in names if n)) or "member"
