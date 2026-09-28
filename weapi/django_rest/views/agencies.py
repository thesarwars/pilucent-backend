from rest_framework import response, status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
    ListAPIView
)
from rest_framework.views import APIView
from rest_framework import filters

from django_filters.rest_framework import DjangoFilterBackend

from datetime import date, timedelta
from django.db.models import Sum

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from agencyio.models import Agency, AgencyTax, AgencyTaxSet
from agencyio.choices import AgencyStatusChoices

from common.django_rest.permissions.company_subscription import HaveSubscription

from salesio.choices import SalesStatusChoices
from salesio.models import Sale

from purchaseio.choices import PurchaseStatus
from purchaseio.models import Purchase

from ..serializers.agencies import (
    PrivateWeAgencyListSerializer,
    PrivateWeAgencyDetailsSerializer,
    PrivateWeAgencyTaxListSerializer,
    PrivateWeAgencyTaxDetailsSerializer,
    CombineAgencyTaxSerializer,
    PrivateWeAgencyTaxSerializer,
    PrivateWeAgencyTaxSetSerializer,
    PrivateWeAgencyTaxTrackerSerializer
)


class PrivateWeAgencyList(ListCreateAPIView):
    serializer_class = PrivateWeAgencyListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_agency_tax"
    

    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
    ]

    filterset_fields = [
        "title",
        "filling_frequency",
        "reporting_method",
        "start_of_period",
    ]
    search_fields = [
        "title",
        "filling_frequency",
        "reporting_method",
        "start_of_period",
    ]

    def get_queryset(self):
        company = self.request.user.get_active_company()
        state = self.request.query_params.get('state')
        queryset = Agency.objects.get_status_active().filter(company=company)
        if state:
            queryset = queryset.filter(state=state)
        return queryset


class PrivateWeAgencyDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeAgencyDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_agency_tax"

    def get_object(self):
        return get_object_or_404(
            Agency.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = AgencyStatusChoices.REMOVED
        instance.save()


class PrivateWeAgencyTaxList(ListCreateAPIView):
    serializer_class = PrivateWeAgencyTaxListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_agency_tax"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    filterset_fields = ["uid", "title"]
    search_fields = ["title"]

    def get_queryset(self):
        return AgencyTax.objects.filter(
            company=self.request.user.get_active_company(),
        )

    def list(self, request, *args, **kwargs):
        last_30_days = date.today() - timedelta(days=30)
        company = self.request.user.get_active_company()

        # Sale
        sales = Sale.objects.filter(
            status__in=[
                SalesStatusChoices.OPEN,
                SalesStatusChoices.ACCEPTED,
                SalesStatusChoices.CLOSED,
            ],
            company=company,
        )

        # Purchase
        purchases = Purchase.objects.filter(
            status__in=[
                PurchaseStatus.OPEN,
                PurchaseStatus.ACCEPTED,
                PurchaseStatus.CLOSED,
            ],
            company=company,
        )

        # Adjustments
        total_adjustments = 0  # TODO : need clarification by kamrul

        purchase_tax_last_30_days = (
            purchases.filter(date__gte=last_30_days).aggregate(
                total_purchases_tax=Sum("total_tax")
            )["total_purchases_tax"]
            or 0
        )

        sale_tax_last_30_days = (
            sales.filter(date__gte=last_30_days).aggregate(
                total_sale_tax=Sum("total_tax")
            )["total_sale_tax"]
            or 0
        )
        total_tax_last_30_days = purchase_tax_last_30_days + sale_tax_last_30_days

        return (
            response.Response(
                {
                    "total_tax_last_30_days": total_tax_last_30_days,
                    "total_sale_tax": sales.aggregate(total_sale_tax=Sum("total_tax"))[
                        "total_sale_tax"
                    ],
                    "total_purchases_tax": purchases.aggregate(
                        total_purchases_tax=Sum("total_tax")
                    )["total_purchases_tax"],
                    "total_adjustments": total_adjustments,
                }
            )
            if request.query_params.get("keywords", None) == "overview"
            else super().list(request, *args, **kwargs)
        )


class PrivateWeAgencyTaxDetails(APIView):
    queryset = AgencyTax.objects.all()
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_agency_tax"

    def delete(self, request, uid):
        # The company filter was commented out, leaving the queryset as
        # `AgencyTax.objects.all()`, so any authenticated user could delete ANY
        # tenant's tax rate by uid. Until the FKs were changed to SET_NULL that
        # cascaded through `SaleItem.tax`, `PurchaseItem.tax`,
        # `CreditNoteItem.tax` and `ProductAdditionalCost.tax` into
        # `JournalEntryConnector`, destroying another company's document lines
        # and their journal legs outright.
        #
        # It was commented out as `agency__company`, which cannot work: AgencyTax
        # has no `agency` field. It holds `company` directly, so restoring the
        # line as written would have raised FieldError -- a 500 -- which is the
        # likely reason it was commented out rather than fixed.
        get_object_or_404(
            self.queryset,
            company=request.user.get_active_company(),
            uid=uid,
        ).delete()
        return response.Response(
            {"error": False, "message": "Deleted successfully", "deleted": True},
            status=status.HTTP_200_OK,
        )


class CombineAgencyTaxViews(ListCreateAPIView):
    queryset = AgencyTax.objects.all()
    serializer_class = PrivateWeAgencyTaxSerializer

    def get_queryset(self):
        return self.queryset.filter(
            company=self.request.user.get_active_company(),

        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context={"company": self.request.user.get_active_company()},
        )

        if serializer.is_valid():
            instance = serializer.save()
            return response.Response(
                {
                    "error": False,
                    "message": "Agency tax created successfully.",
                    "data": self.get_serializer(instance).data,
                },
                status=status.HTTP_201_CREATED,
            )
        else:
            return response.Response(
                {
                    "error": True,
                    "message": "Validation failed.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


# agency tax set

class AgencyTaxSetViews(ListAPIView):
    serializer_class = PrivateWeAgencyTaxSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_agency_tax"

    def get_queryset(self):
        company = self.request.user.get_active_company()
        state = self.request.query_params.get('state')
        
        # Get AgencyTax objects that have tax_groups (AgencyTaxSet)
        if state:
            # Filter by state through the agency relationship in tax_groups
            queryset = AgencyTax.objects.filter(
                company=company,
                tax_groups__agency__state=state
            ).distinct()
            # print("filtered by state:", state, queryset)
        else:
            # Get all AgencyTax objects for the company that have tax_groups
            queryset = AgencyTax.objects.filter(
                company=company,
                tax_groups__isnull=False
            ).distinct()
        
        return queryset


class PrivateWeAgencyTaxTracker(APIView):
	# permission_classes = [HaveSubscription, IsGroupPermission]
	required_feature = "is_agency_tax"

	def get(self, request, uid):
		agency = get_object_or_404(
			Agency.objects.get_status_active(),
			company=request.user.get_active_company(),
			uid=uid,
		)
		
		serializer = PrivateWeAgencyTaxTrackerSerializer(
			{},
			agency=agency,
			current_date=date.today()
		)
		
		return response.Response(
			{
				"error": False,
				"message": "Tax tracking data retrieved successfully",
				"data": serializer.data,
			},
			status=status.HTTP_200_OK,
		)