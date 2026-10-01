from rest_framework.serializers import Serializer, SlugRelatedField, ValidationError

from accounts.models import User

from companyio.models import Company

from common.django_rest.helpers.tasks import send_email

from employeeio.choices import EmployeeStatusChoices


class EmployeeOnboardSerializer(Serializer):
    user_uid = SlugRelatedField(
        slug_field="uid", queryset=User.objects.filter(), write_only=True
    )
    company_uid = SlugRelatedField(
        slug_field="uid", queryset=Company.objects.filter(), write_only=True
    )

    def validate(self, attrs):
        user = attrs["user_uid"]
        company = attrs["company_uid"]
        employee = user.get_employee()
        if (
            not employee
            or user.get_active_company() != company
            or employee.status != EmployeeStatusChoices.DRAFT
        ):
            raise ValidationError({"message": "Invalid."})
        return attrs

    def create(self, validate_data):
        user = validate_data["user_uid"]
        employee = user.get_employee()
        employee.status = EmployeeStatusChoices.ACTIVE
        employee.is_joined = True
        employee.save_dirty_fields()
        send_email(
            {"email": user.email, "password": user.email},
            "emails/onboard/employee_email_and_password.html",
            user.email,
            "Your Pilucent email and password",
        )
        return validate_data
