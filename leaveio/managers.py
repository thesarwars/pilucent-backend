from django.db import models

from .choices import LeaveStatusChoices


class LeaveTypeQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=LeaveStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=LeaveStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=LeaveStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=LeaveStatusChoices.DRAFT)



class LeaveRequestQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=LeaveStatusChoices.REMOVED)
    
    def get_status_active(self):
        return self.filter(status=LeaveStatusChoices.ACTIVE)
    
    def get_status_pending(self):
        return self.filter(status=LeaveStatusChoices.PENDING)
    
    def get_status_draft(self):
        return self.filter(status=LeaveStatusChoices.DRAFT)
    

class LeaveBalanceQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=LeaveStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=LeaveStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=LeaveStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=LeaveStatusChoices.DRAFT)


class LeaveEncashmentQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=LeaveStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=LeaveStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=LeaveStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=LeaveStatusChoices.DRAFT)