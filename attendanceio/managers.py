from django.db import models

from .choices import AttendanceStatusChoices, HolidayStatusChoices


class AttendanceQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=AttendanceStatusChoices.REMOVED)

    def get_status_present(self):
        return self.filter(status=AttendanceStatusChoices.PRESENT)

    def get_status_absent(self):
        return self.filter(status=AttendanceStatusChoices.ABSENT)

    def get_status_leave(self):
        return self.filter(status=AttendanceStatusChoices.LEAVE)

    def get_status_late(self):
        return self.filter(status=AttendanceStatusChoices.LATE_ARRIVAL)

    def get_status_early(self):
        return self.filter(status=AttendanceStatusChoices.EARLY_DEPARTURE)


class HolidayQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=HolidayStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=HolidayStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=HolidayStatusChoices.PENDING)

    def get_status_removed(self):
        return self.filter(status=HolidayStatusChoices.REMOVED)
