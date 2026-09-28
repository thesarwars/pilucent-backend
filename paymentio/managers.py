
from django.db import models
from .choices import PaymentMethodStatusChoices

class PaymentMethodQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=PaymentMethodStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=PaymentMethodStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=PaymentMethodStatusChoices.INACTIVE)

    def get_status_draft(self):
        return self.filter(status=PaymentMethodStatusChoices.DRAFT)
