"""Sites (establishments). Every company has one default site, created on
first use; an employee with no site of their own is on it."""

from django.db import IntegrityError, transaction

from ..models import Site


def default_site(company):
    found = Site.objects.filter(company=company, is_default=True).first()
    if found is not None:
        return found
    try:
        with transaction.atomic():
            return Site.objects.create(company=company, code="MAIN", name="Main site", is_default=True)
    except IntegrityError:  # created meanwhile
        return Site.objects.get(company=company, is_default=True)


def site_of(employee):
    return employee.site if employee.site_id else default_site(employee.company)


def sites_of(company):
    default_site(company)
    return list(Site.objects.filter(company=company, is_active=True))
