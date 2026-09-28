from rest_framework.response import Response
from rest_framework import status
from django.db.models import Prefetch
from accounts.models import User
from adminio.django_rest.serializers.admin_permissions import RoleAndPermissionSerializer, GroupPermissionsListSerializer
from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from django.contrib.auth.models import Permission, Group
from rest_framework.views import APIView


# Create your views here.


class AdminUserPermissionsView(APIView):
    queryset = User.objects.all()
    serializer_class = RoleAndPermissionSerializer
    permission_classes = [IsGroupPermission]
    
    def get(self, request, user_uid):
        try:
            queryset = self.queryset.filter(uid=user_uid)
            serializer = self.serializer_class(queryset, many=True)
            return Response(serializer.data, status.HTTP_200_OK)
        except Exception as e:
            return Response(str(e), status.HTTP_400_BAD_REQUEST)


class GroupPermissionsListView(APIView):
    queryset = Group.objects.all()
    serializer_class = GroupPermissionsListSerializer
    permission_classes = [IsGroupPermission]

    def get(self, request):
        try:
            permissions_qs = Permission.objects.select_related("content_type").only(
                "id", "codename", "content_type__app_label", "content_type__model"
            )
            queryset = self.queryset.filter(name="admin").prefetch_related(
                Prefetch("permissions", queryset=permissions_qs)
            )
            serializer = self.serializer_class(queryset, many=True)
            return Response(serializer.data, status.HTTP_200_OK)
        except Exception as e:
            return Response(str(e), status.HTTP_400_BAD_REQUEST)