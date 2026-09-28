from django.db import models
from common.models import BaseModelWithUID
from autoslug import AutoSlugField
from .django_rest.helpers.slug_helpers import get_leave_type_slug
from .choices import (
    LeaveTypeChoice,
    LeaveStatusChoices,
    LeaveBalanceStatusChoices,
    EmployeeLeaveRequestStatusChoices,
    LeaveEncashmentStatusChoices,
)
from .managers import (
    LeaveTypeQuerySet,
    LeaveRequestQuerySet,
    LeaveEncashmentQuerySet,
    LeaveBalanceQuerySet,
)
from django.utils import timezone


class LeaveType(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_leave_type_slug, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=100, blank=True, null=True)
    definition = models.TextField(blank=True, null=True)
    color = models.CharField(max_length=7, default="#3b82f6")

    maximum_allocation = models.PositiveIntegerField(null=True, blank=True)
    allow_after_working_days = models.PositiveIntegerField(null=True, blank=True)
    max_consecutive_allowed = models.PositiveIntegerField(null=True, blank=True)
    maximum_allocation_hours = models.PositiveIntegerField(null=True, blank=True)

    leave_type = models.CharField(
        max_length=20,
        choices=LeaveTypeChoice.choices,
        default=LeaveTypeChoice.DAILY,
    )
    # Carry Forward
    is_carry_forward = models.BooleanField(default=False)
    max_carry_forwarded = models.PositiveIntegerField(null=True, blank=True)
    carry_expiry_days = models.PositiveIntegerField(null=True, blank=True)

    # Encashment
    is_encashable = models.BooleanField(default=False)
    max_encashable = models.PositiveIntegerField(null=True, blank=True)
    min_encashable = models.PositiveIntegerField(null=True, blank=True)
    earning_components = models.TextField(blank=True)

    # Earned Leave
    is_earned_leave = models.BooleanField(default=False)
    earned_leave_frequency = models.CharField(max_length=100, blank=True)
    allocate_on_day = models.CharField(max_length=20, blank=True)
    rounders = models.CharField(max_length=10, blank=True)

    # Salary and Payment
    is_partially_paid = models.BooleanField(default=False)
    fraction_salary_per_leave = models.FloatField(null=True, blank=True)

    # Flags
    is_leave_without_pay = models.BooleanField(default=False)
    allow_negative_balance = models.BooleanField(default=False)
    include_holidays_within_leave = models.BooleanField(default=False)
    is_optional_leave = models.BooleanField(default=False)
    allow_over_allocation = models.BooleanField(default=False)
    is_compensatory = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=LeaveStatusChoices.choices,
        default=LeaveStatusChoices.ACTIVE,
    )

    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    objects = LeaveTypeQuerySet.as_manager()

    def __str__(self):
        return self.display_name or self.name


class LeaveBalance(BaseModelWithUID):
    leave_year = models.PositiveIntegerField(default=timezone.now().year)
    from_date = models.DateField(null=True, blank=True)
    to_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=LeaveBalanceStatusChoices.choices,
        default=LeaveBalanceStatusChoices.ACTIVE,
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leave_balance_created_by",
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    objects = LeaveBalanceQuerySet.as_manager()

    def __str__(self):
        return f"Leave Balance {self.leave_year} ({self.from_date} to {self.to_date})"


class EmployeeLeaveAllocation(BaseModelWithUID):
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)
    leave_type = models.ForeignKey("leaveio.LeaveType", on_delete=models.CASCADE)
    leave_balance = models.ForeignKey(
        "leaveio.LeaveBalance",
        on_delete=models.CASCADE,
        related_name="allocations",
        null=True,
        blank=True,
    )
    leave_year = models.PositiveIntegerField(default=timezone.now().year)
    allocated_days = models.PositiveIntegerField(default=0, blank=True, null=True)
    used_days = models.PositiveIntegerField(default=0, blank=True, null=True)

    # Core values
    opening_balance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    allocated = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    used = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    encashed = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    adjusted = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    created_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leave_allocation_created_by",
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    @property
    def available_balance(self):
        return max(
            (self.opening_balance + self.allocated + self.adjusted)
            - (self.used + self.encashed),
            0.0,
        )

    @property
    def available_days(self):
        return max(
            (
                (self.allocated_days - self.used_days)
                if self.allocated_days is not None
                else 0
            ),
            0,
        )

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.leave_year})"


class LeaveRequest(BaseModelWithUID):
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)
    leave_type = models.ForeignKey("leaveio.LeaveType", on_delete=models.CASCADE)
    from_date = models.DateField(blank=True, null=True)
    to_date = models.DateField(blank=True, null=True)
    total_days = models.PositiveIntegerField(default=0, blank=True, null=True)
    status = models.CharField(
        max_length=50,
        choices=EmployeeLeaveRequestStatusChoices.choices,
        default=EmployeeLeaveRequestStatusChoices.PENDING,
    )
    note = models.TextField(blank=True, null=True)
    assigned_to = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_to",
    )
    approved_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_by",
    )
    is_active = models.BooleanField(default=True)

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    employee_shift = models.ForeignKey(
        "companyio.CompanyShift", blank=True, null=True, on_delete=models.SET_NULL
    )

    objects = LeaveRequestQuerySet.as_manager()

    def __str__(self):
        return (
            f"{self.employee} - {self.leave_type} ({self.from_date} to {self.to_date})"
        )


class LeaveEncashment(BaseModelWithUID):
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)
    encashment_date = models.DateField(default=timezone.now)
    leave_balance = models.ForeignKey("leaveio.LeaveBalance", on_delete=models.CASCADE)
    total_encashment_amount = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    status = models.CharField(
        max_length=20,
        choices=LeaveEncashmentStatusChoices,
        default=LeaveEncashmentStatusChoices.ACTIVE,
    )
    created_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leave_encashment_created_by",
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    objects = LeaveEncashmentQuerySet.as_manager()

    def __str__(self):
        return (
            f"{self.employee} - {self.encashment_date} - {self.total_encashment_amount}"
        )


class LeaveEncashmentItem(BaseModelWithUID):
    encashment = models.ForeignKey(
        "leaveio.LeaveEncashment", on_delete=models.CASCADE, related_name="items"
    )
    leave_type = models.ForeignKey("leaveio.LeaveType", on_delete=models.CASCADE)
    leave_allocation = models.ForeignKey(
        "leaveio.EmployeeLeaveAllocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    leave_balance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    actual_encashable_days = models.PositiveIntegerField(
        default=0, blank=True, null=True
    )
    encashment_days = models.PositiveIntegerField(default=0, blank=True, null=True)
    amount_per_day = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    def __str__(self):
        return f"{self.leave_type} - {self.encashment_days} days - {self.total_amount}"


class LeaveRequests(LeaveRequest):
    """Proxy model for LeaveRequest to provide independent 'Leave Request' permissions."""

    class Meta:
        proxy = True
        verbose_name = "Leave Request"
        verbose_name_plural = "Leave Requests"


class LeaveApproval(LeaveRequest):
    """Proxy model for LeaveRequest to provide independent 'Leave Approval' permissions."""

    class Meta:
        proxy = True
        verbose_name = "Leave Approval"
        verbose_name_plural = "Leave Approvals"
