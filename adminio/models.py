from django.core.exceptions import ValidationError
from django.contrib.auth.models import Permission
from django.db import models

from common.models import BaseModelWithUID

from .choices import CompanyRoleKindChoices, CompanyRoleStatusChoices


class CompanyRole(BaseModelWithUID):
    name = models.CharField(max_length=255)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    kind = models.CharField(
        max_length=20,
        choices=CompanyRoleKindChoices.choices,
        default=CompanyRoleKindChoices.USER,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=CompanyRoleStatusChoices.choices,
        default=CompanyRoleStatusChoices.ACTIVE,
        db_index=True,
    )
    is_system = models.BooleanField(
        default=False,
        db_index=True,
        help_text="System roles are seeded per company (admin/user/employee) and cannot be deleted or have their name/kind changed.",
    )
    description = models.TextField(blank=True, null=True)
    permission = models.ManyToManyField(Permission, blank=True)

    class Meta:
        unique_together = ("company", "name")

    def __str__(self):
        return f"{self.name}_{self.company.name}"

    def clean(self):
        if self.pk and self.is_system:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and (
                original.name != self.name
                or original.kind != self.kind
                or original.is_system != self.is_system
            ):
                raise ValidationError(
                    "System roles cannot have their name, kind, or is_system flag changed."
                )

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError("System roles cannot be deleted.")
        return super().delete(*args, **kwargs)
