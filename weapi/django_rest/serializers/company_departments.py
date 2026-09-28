from rest_framework.serializers import ModelSerializer, ValidationError

from companyio.models import CompanyDepartment


class PrivateWeCompanyDepartmenListSerializer(ModelSerializer):
    class Meta:
        model = CompanyDepartment
        fields = ["uid", "title", "code"]
        read_only_fields = ["uid", "created_at", "updated_at"]

    def validate(self, attrs):
        title = attrs.get("title")
        if title:
            company = self.context["request"].user.get_active_company()
            # Unique per company among ACTIVE departments only (a removed/inactive
            # title can be reused). Company scope also stops another tenant's
            # identically-named department from tripping "already exists".
            if (
                CompanyDepartment.objects.get_status_active()
                .filter(company=company, title=title)
                .exists()
            ):
                raise ValidationError({"message": "Department already exists."})
        return super().validate(attrs)

    def create(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        return super().create(validated_data)


class PrivateWeCompanyDepartmenDetailsSerializer(ModelSerializer):
    class Meta:
        model = CompanyDepartment
        fields = ["uid", "title", "code"]
        read_only_fields = ["uid", "created_at", "updated_at"]
    