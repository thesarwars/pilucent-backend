from rest_framework.serializers import ModelSerializer, ValidationError

from companyio.models import CompanyDesignation


class PrivateWeCompanyDesignationListSerializer(ModelSerializer):

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        title = attrs.get("title")
        # Unique per company among ACTIVE designations only (removed/inactive
        # titles are reusable) — mirrors the partial DB UniqueConstraint.
        if title and CompanyDesignation.objects.get_status_active().filter(
            company=company, title=title
        ).exists():
            raise ValidationError({"message": "Designation already exists"})

        attrs["company"] = company
        return super().validate(attrs)

    class Meta:
        model = CompanyDesignation
        fields = ["uid", "title", "code", "status", "created_at", "updated_at"]
        read_only_fields = ["uid", "created_at", "updated_at"]


class PrivateWeCompanyDesignationDetailsSerializer(ModelSerializer):

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        title = attrs.get("title")
        if title:
            clash = CompanyDesignation.objects.get_status_active().filter(
                company=company, title=title
            )
            # Exclude the row being updated, else re-saving with an unchanged
            # title matches itself and falsely reports "already exists".
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise ValidationError({"message": "Designation already exists"})

        attrs["company"] = company
        return super().validate(attrs)

    class Meta:
        model = CompanyDesignation
        fields = ["uid", "title", "code", "status", "created_at", "updated_at"]
        read_only_fields = ["uid", "created_at", "updated_at"]
