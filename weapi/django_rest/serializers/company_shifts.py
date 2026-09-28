from rest_framework.serializers import ModelSerializer, ValidationError, CharField

from companyio.models import CompanyShift


class PrivateWeCompanyShiftListSerializer(ModelSerializer):
    workable_hour = CharField(source="get_workable_hour", read_only=True)

    class Meta:
        model = CompanyShift
        fields = [
            "uid",
            "title",
            "status",
            "code",
            "description",
            "kind",
            # shift sedule
            "regular_hour",
            "grace_time",
            "in_time",
            "out_time",
            "workable_hour",
            # Lunch
            "lunch_time",
            "lunch_in_time",
            "lunch_out_time",
            # Tiffin
            "tiffin_time",
            "tiffin_in_time",
            "tiffin_out_time",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "created_at", "updated_at"]

    def validate(self, attrs):
        title = attrs.get("title")
        if title:
            company = self.context["request"].user.get_active_company()
            # A title must be unique per company among ACTIVE shifts only.
            # CompanyShift has no RLS, so an unscoped filter collided across every
            # tenant (any company's "Morning" blocked everyone); and only active
            # shifts should reserve a title (draft/inactive/removed shifts don't).
            if (
                CompanyShift.objects.get_status_active()
                .filter(company=company, title=title)
                .exists()
            ):
                raise ValidationError({"message": "Shift already exists."})
        return super().validate(attrs)

    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["created_by"] = user
        validated_data["company"] = company
        return super().create(validated_data)


class PrivateWeCompanyShiftDetailsSerializer(ModelSerializer):
    workable_hour = CharField(source="get_workable_hour")

    class Meta:
        model = CompanyShift
        fields = [
            "uid",
            "title",
            "status",
            "code",
            "description",
            "kind",
            # shift sedule
            "regular_hour",
            "grace_time",
            "in_time",
            "out_time",
            "workable_hour",
            # Lunch
            "lunch_time",
            "lunch_in_time",
            "lunch_out_time",
            # Tiffin
            "tiffin_time",
            "tiffin_in_time",
            "tiffin_out_time",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "workable_hour", "created_at", "updated_at"]
