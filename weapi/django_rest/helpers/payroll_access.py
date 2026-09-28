from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

PAYROLL_PERMISSION_CLASSES = [HaveSubscription, IsGroupPermission]
PAYROLL_REQUIRED_FEATURE = "is_payroll"
