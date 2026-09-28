from rest_framework import serializers
from companyio.models import Company, CompanyUser
from accounts.models import User


class CompanyUsersSerializer(serializers.ModelSerializer):
    user_uid = serializers.CharField(source="user.uid", read_only=True)
    username = serializers.CharField(source="user.name", read_only=True)
    is_admin = serializers.CharField(source="user.is_admin", read_only=True)
    
    class Meta:
        model = CompanyUser
        fields = ["user_uid", "username", "is_admin"]


class AdminCompanyListSerializer(serializers.ModelSerializer):
    user_uid = serializers.CharField(required=False)
    company_users = CompanyUsersSerializer(many=True, read_only=True, source="companyuser_set")
    legal_address = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Company
        fields = [
            "uid",
            "name",
            "legal_name",
            "kind",
            "status",
            "business_id_no",
            "vat_number",
            "time_zone",
            "email",
            "phone",
            "website",
            "company_addresses",
            "customer_facing_address",
            "legal_address",
            # "logo",
            "created_at",
            "updated_at",
            "user_uid",
            "company_users",
        ]
        # Must be inside Meta -- on the class body DRF ignores it entirely.
        # `status` stays WRITABLE here, unlike the company-facing serializers:
        # this is the superadmin console, and PATCHing status back to ACTIVE is
        # the only way to undo a tenant removal.
        read_only_fields = ["uid", "created_at", "updated_at", "legal_address"]

    def get_legal_address(self, obj):
        return obj.get_legal_address()

    # def get_company_user(self, attr):
        
    
    def validate(self, attrs):
        user = attrs.get("user_uid")
        if CompanyUser.objects.filter(user__uid=user).exists():
            raise serializers.ValidationError({"message": "Company alredy exists."})

        attrs["user_uid"] = user
        return super().validate(attrs)

    def create(self, validated_data):
        user_uid = validated_data.pop("user_uid", None)
        user = User.objects.get(uid=user_uid)
        company = Company.objects.create(**validated_data)

        # Creating company user
        CompanyUser.objects.create(company=company, user=user)
        return company
    
    
class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["uid", "email", "is_admin"]