from django.db import models

from .choices import CustomerStatusChoices

class CustomerQuerySet(models.QuerySet):
    def selectable(self):
        """Customers a user may choose when building a new document.

        The picker half of deactivation. An inactive customer keeps their
        balance, their history and their place on the ageing report -- they are
        withheld from data entry and nothing else -- so this is narrower than
        `get_status_all()`, which excludes only REMOVED and is what reports and
        resolvers keep using.

        Narrower by exactly one state, and no more. The account version of this
        first filtered to ACTIVE, which reads as the same thing and is not:
        `status` defaults to DRAFT on the model, so every row created without an
        explicit status vanished from every picker at once. 73 tests found it.
        Production holds 2 PENDING customers today, and they must keep working.
        """
        return self.exclude(
            status__in=[
                CustomerStatusChoices.REMOVED,
                CustomerStatusChoices.INACTIVE,
            ]
        )

    def get_status_all(self):
        return self.all().exclude(status=CustomerStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=CustomerStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=CustomerStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=CustomerStatusChoices.DRAFT)
