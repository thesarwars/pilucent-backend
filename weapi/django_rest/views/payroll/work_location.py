
from rest_framework import filters
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, get_object_or_404, ListAPIView
from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from payrollio.models import PayrollWorkLocation
from weapi.django_rest.serializers.payroll.work_location import (
	PayrollWorkLocationSlimSerializer,
	PayrollWorkLocationDetailsSerializer,
)

from payrollio.choicess import PayrollWorkLocationChoices

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)
 

class PayrollWorkLocationListCreateView(ListCreateAPIView):
	serializer_class = PayrollWorkLocationSlimSerializer
	permission_classes = PAYROLL_PERMISSION_CLASSES
	required_feature = PAYROLL_REQUIRED_FEATURE
	filter_backends = [
		filters.SearchFilter,
		filters.OrderingFilter,
		DjangoFilterBackend,
	]
	ordering_fields = ["created_at"]
	search_fields = ["title", "location_address"]
	filterset_fields = ["status"]

	def get_queryset(self):
		return PayrollWorkLocation.objects.get_status_all().filter(
			company=self.request.user.get_active_company()
		)


class PayrollWorkLocationDetailView(RetrieveUpdateDestroyAPIView):
	serializer_class = PayrollWorkLocationDetailsSerializer
	permission_classes = PAYROLL_PERMISSION_CLASSES
	required_feature = PAYROLL_REQUIRED_FEATURE
	 
	def get_object(self):
		return get_object_or_404(
			PayrollWorkLocation.objects.get_status_all(),
			company=self.request.user.get_active_company(),
			uid=self.kwargs["uid"],
		)

	def perform_destroy(self, instance):
		if instance.is_primary:
			raise ValidationError(
				{"detail": "Primary work location cannot be deleted."}
			)
		if instance.employees.exists():
			raise ValidationError(
				{
					"detail": (
						"Work location cannot be deleted while employees are assigned to it."
					)
				}
			)
		instance.status = PayrollWorkLocationChoices.REMOVED
		instance.save()
		

class PayrollWorkLocationListNoPaginationView(ListAPIView):
    serializer_class = PayrollWorkLocationSlimSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "location_address", "location_state"]
    filterset_fields = ["status"]
    pagination_class = None

    def get_queryset(self):
        return PayrollWorkLocation.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )
