from rest_framework.generics import RetrieveAPIView

from companyio.models import CompanyShift

from ..serializer.shifts import PrivateMeShiftDetailsSerializer


class PrivateMeShiftDetails(RetrieveAPIView):
    serializer_class = PrivateMeShiftDetailsSerializer

    def get_object(self):
        return self.request.user.get_employee().shift
