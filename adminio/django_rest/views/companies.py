from companyio.choices import CompanyStatusChoices
from companyio.models import Company
from accounts.models import User
from rest_framework import views, permissions, status, response, generics
from adminio.mixins import IsSuperAdmin
from adminio.django_rest.serializers.companies import AdminCompanyListSerializer, AdminUserSerializer
from datetime import timedelta, datetime


class AdminCompanyList(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    queryset = Company.objects.all()
    serializer_class = AdminCompanyListSerializer
    # print()
    # def get_queryset(self):
    #     return Company.objects.all()
    
    def list(self, request):
        try:
            # Removed companies are excluded everywhere here. Deleting a tenant is
            # soft (status=REMOVED) because the ledger has to survive, so without
            # this filter a "deleted" company kept appearing in the console and
            # counted towards the totals.
            live = Company.objects.exclude(status=CompanyStatusChoices.REMOVED)

            total_company = live.count()
            active_company = live.filter(status=CompanyStatusChoices.ACTIVE).count()
            inactive_company = live.filter(status=CompanyStatusChoices.INACTIVE).count()
            removed_company = Company.objects.filter(
                status=CompanyStatusChoices.REMOVED
            ).count()
            new_company = live.filter(created_at__gte=(datetime.now()-timedelta(days=7))).count()

            serializers = self.get_serializer(live, many=True)

            return response.Response({"total_company" : total_company, "active_company" : active_company, "inactive_company" :inactive_company, "removed_company" : removed_company, "new_company" : new_company, "data" : serializers.data}, status.HTTP_200_OK)
            
        except Exception as e:
            return response.Response({"error" : True, "message" : str(e)}, status.HTTP_400_BAD_REQUEST)
        

class AdminCompanyRetrieve(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsSuperAdmin]
    queryset = Company.objects.all()
    serializer_class = AdminCompanyListSerializer
    lookup_field = "uid"

    def perform_destroy(self, instance):
        """Deactivate the tenant; never erase it.

        This used to hard-delete the Company row. Everything a tenant owns
        cascades off it -- chart of accounts, journal entries, customers,
        products, sales -- so a single DELETE destroyed the entire ledger with no
        reversing entry and nothing to reconstruct it from.

        `JournalEntryConnector.account` is now PROTECT, which would make that
        DELETE raise instead (PROTECT fires even inside a cascade). Rather than
        leave a superadmin endpoint that reliably 409s, it now does the thing
        that was actually wanted: mark the company REMOVED and keep the books.
        """
        instance.status = CompanyStatusChoices.REMOVED
        instance.save(update_fields=["status", "updated_at"])
    
    # def get_queryset(self):
    #     queryset = self.get_queryset()
    #     serializer = self.serializer_class(queryset)
    #     return serializer.data
    

class AdminUserRetrieve(generics.RetrieveAPIView):
    permission_classes = [IsSuperAdmin]
    queryset = User.objects.all()
    serializer_class = AdminUserSerializer
    lookup_field = "email"
    
    # def get_queryset(self):
    #     qs = self.get_queryset()
    #     return super().get_queryset()
    