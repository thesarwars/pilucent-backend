from django.db import models
from .choices import TransactionStatusChoices

class TransactionQuerySet(models.QuerySet):
    def non_spam(self):
        return self.filter(is_spam=False)

    def spam(self):
        return self.filter(is_spam=True)

    def by_category(self, category):
        return self.filter(category=category)

    def get_status_review(self):
        return self.filter(transaction_status=TransactionStatusChoices.FOR_REVIEW)