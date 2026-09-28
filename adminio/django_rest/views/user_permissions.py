from rest_framework.response import Response
from rest_framework import status
from adminio.django_rest.serializers.user_permissions import CompanyUserPermissionSerializer, CompanyUserPermsListSerializer
from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from companyio.models import CompanyUser
from rest_framework.views import APIView
from rest_framework import generics

# Create your views here.
        

class PermissionsToCompanyUser(APIView):
    """This API for admin, who will assign permission to his employee. 
    So it needs to check from 'Group' name and permissions"""
    
    queryset = CompanyUser.objects.all()
    serializer_class = CompanyUserPermissionSerializer
    permission_classes = [IsGroupPermission]
    
    def patch(self, request, company_uid):
        try:
            company_user = self.queryset.get(user__uid=request.data["user_uid"], company__uid=company_uid)
            serializer = self.serializer_class(instance=company_user, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response({"message":"Assigned", "error" : False}, status.HTTP_201_CREATED)
            return Response({"message" : serializer.errors, "error"  : True}, status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(str(e), status.HTTP_400_BAD_REQUEST)


class ViewPermissionsOfUser(generics.ListAPIView):
    queryset = CompanyUser.objects.all()
    serializer_class = CompanyUserPermsListSerializer
    permission_classes = [IsGroupPermission]
    
    def list(self, request):
        try:
            # role_uid = request.GET["role_uid"]
            company_uid = request.GET["company_uid"]
            user_uid = request.GET["user_uid"]
            # if self.has_group_permission(request, company_uid):
            queryset = self.queryset.filter(user__uid=user_uid, company__uid=company_uid)
            serializer = self.serializer_class(queryset, many=True)
            return Response(serializer.data, status.HTTP_200_OK)
            # return Response({"message": "not allowed"}, status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response(str(e), status.HTTP_400_BAD_REQUEST)

