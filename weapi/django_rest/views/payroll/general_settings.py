from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, get_object_or_404
from rest_framework.response import Response
from rest_framework import status
from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from payrollio.models import PayrollGeneralSettings
from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)
from weapi.django_rest.serializers.payroll.general_settings import (
    PayrollGeneralSettingsSerializer,
)

class PayrollGeneralSettingsRetrieveUpdateView(RetrieveUpdateDestroyAPIView):
    serializer_class = PayrollGeneralSettingsSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    
    def get_object(self):
        company = self.request.user.get_active_company()
        obj, created = PayrollGeneralSettings.objects.get_or_create(
            company=company,
            defaults={"created_by": self.request.user.get_employee()}
        )
        return obj