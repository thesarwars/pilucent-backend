"""§9 events. Each is written twice, in the transaction that caused it: to
the outbox (`LeaveEvent`), which a consumer such as payroll reads and marks
consumed, and as notifications to the people who act on it. A write that
rolls back -- a bulk preview, a refused approval -- takes both with it.
"""

from django.db.models import Q

from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME
from notificationio.choices import NotificationModelKindChoices, NotificationStatusChoices
from notificationio.services.notifications import NotificationService

from ..choices import LeaveEventChoices as E
from ..models import LeaveEvent

APP = "leaveledgerio"

# Event -> (notification kind, who hears about it)
ROUTES = {
    E.LEAVE_REQUESTED: ("LEAVE_REQUESTED", ("approve_leave",)),
    E.LEAVE_APPROVED: ("LEAVE_APPROVED", ("employee", "requester")),
    E.LEAVE_DECLINED: ("LEAVE_DECLINED", ("employee", "requester")),
    E.BALANCE_GRANTED: ("LEAVE_BALANCE_GRANTED", ("employee",)),
    E.ACCRUAL_POSTED: ("LEAVE_ACCRUAL_POSTED", ("employee",)),
    E.FORFEITED: ("LEAVE_FORFEITED", ("employee",)),
    E.ENCASHMENT_APPROVED: ("ENCASHMENT_APPROVED", ("employee", "approve_encashment")),
    E.MATERNITY_CASE_OPENED: ("MATERNITY_CASE_OPENED", ("read_maternity_restricted",)),
    E.MATERNITY_PAYMENT_DUE: ("MATERNITY_PAYMENT_DUE", ("approve_encashment", "read_maternity_restricted")),
    E.CREDIT_EARNED: ("COMPENSATORY_CREDIT_EARNED", ("employee",)),
}


def holders(company, codename):
    """Users in this company who hold `leaveledgerio.codename`: its admins, and
    anyone whose role or overlay grants it."""
    from accounts.models import User

    held = (Q(companyuser__company=company, companyuser__roles__company=company,
              companyuser__roles__name=ADMIN_GROUP_NAME, companyuser__roles__is_system=True)
            | Q(companyuser__company=company, companyuser__roles__permission__codename=codename,
                companyuser__roles__permission__content_type__app_label=APP)
            | Q(companyuser__company=company, companyuser__permission__codename=codename,
                companyuser__permission__content_type__app_label=APP))
    return list(User.objects.filter(held).exclude(status__in=["INACTIVE", "REMOVED"]).distinct())


def emit(company, name, *, employee=None, entity_ref="", payload=None, message="", requester=None, actor=None):
    """Write the event and notify. `actor` is not notified of their own act."""
    event = LeaveEvent.objects.create(company=company, name=name, employee=employee, entity_ref=entity_ref,
                                      payload=payload or {})
    kind, audiences = ROUTES[name]
    users = {}
    for audience in audiences:
        if audience == "employee":
            if employee is not None and employee.user_id and employee.user.status not in ("INACTIVE", "REMOVED"):
                users[employee.user_id] = employee.user
        elif audience == "requester":
            if requester is not None:
                users[requester.pk] = requester
        else:
            for u in holders(company, audience):
                users[u.pk] = u
    if actor is not None:
        users.pop(getattr(actor, "pk", None), None)
    NotificationService.create_notification(
        status=NotificationStatusChoices.PUBLISHED, model_kind=NotificationModelKindChoices.LEAVE, kind=kind,
        message=(message or name)[:100], is_company=True, users=list(users.values()))
    return event


def pending(company, name=None):
    qs = LeaveEvent.objects.filter(company=company, consumed_at__isnull=True)
    return qs.filter(name=name) if name else qs
