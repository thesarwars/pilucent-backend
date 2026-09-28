"""Serializers for the BD employee API (`docs/employee-profile.md` §9).

Wire conventions:

* keys are camelCase, the front end's names (`nameEn`, `pfEmployee`, ...);
* money is a decimal string, never a float, in either direction;
* dates are `YYYY-MM-DD`;
* validation errors are addressed by the UI's field ids (`f-nid`, `f-etin`,
  ...) so the client can focus the offending input -- see `ui_errors`.

Tenancy: every lookup here is scoped by the company in the serializer
context. A uid or code from another company is "not found", never resolved.
"""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from common import clock
from common.money import money_str
from companyio.models import CompanyDepartment, CompanyDesignation, CompanySection, CompanyShift
from employeeio.choices import ClassificationChoices, PaymentMethodChoices, TrackedFieldChoices
from employeeio.models import (
    CompanyStatutoryProfile,
    Employee,
    EmployeeFieldHistory,
    EmployeeInvestment,
    EmployeeNominee,
    EmployeePaymentProfile,
    EmployeeSalaryStructure,
    EmployeeStatutory,
    EmployeeTaxProfile,
)
from employeeio.services import validation
from employeeio.ui import FIELD_IDS
from rulebookio.book import rule_book


def camel(name):
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def snake(name):
    return re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()


def snake_map(fields):
    return {camel(f): f for f in fields}


def ui_errors(errors):
    """DRF `serializer.errors` -> `{"errors": [{field, path, messages}]}`, where
    `field` is the UI input id when the UI has one."""
    out = []
    for key, messages in errors.items():
        key = snake(key)
        if isinstance(messages, dict):
            messages = [f"{k}: {v}" for k, v in messages.items()]
        elif not isinstance(messages, (list, tuple)):
            messages = [messages]
        flat = []
        for row, m in enumerate(messages, 1):
            if isinstance(m, dict):  # one entry of a list, e.g. a nominee
                flat.extend(f"Row {row} {camel(k)}: {' '.join(map(str, v))}" for k, v in m.items())
            else:
                flat.extend(m if isinstance(m, list) else [m])
        out.append({
            "field": FIELD_IDS.get(key, camel(key)),
            "path": camel(key),
            "messages": [str(m) for m in flat],
        })
    return {"errors": out}


class MoneyField(serializers.DecimalField):
    """Decimal string in, decimal string out. A JSON float is refused."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 19)
        kwargs.setdefault("decimal_places", 3)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if isinstance(data, float):
            raise serializers.ValidationError("Send amounts as decimal strings, not numbers with a fraction.")
        return super().to_internal_value(data)

    def to_representation(self, value):
        return money_str(value)


class CamelModelSerializer(serializers.ModelSerializer):
    """ModelSerializer that speaks camelCase and refuses unknown keys, so a
    field the client thinks it saved can never be silently dropped."""

    def to_representation(self, instance):
        return {camel(k): v for k, v in super().to_representation(instance).items()}

    def to_internal_value(self, data):
        if hasattr(data, "getlist"):  # multipart: keep files, take single values
            data = {k: data.get(k) for k in data.keys()}
        mapping = snake_map(self.fields.keys())
        writable = {name for name, f in self.fields.items() if not f.read_only}
        unknown = [k for k in data if k not in mapping or mapping[k] not in writable]
        if unknown:
            raise serializers.ValidationError({
                k: ["Not a writable field here."] for k in unknown
            })
        return super().to_internal_value({mapping[k]: v for k, v in data.items()})

    def build_standard_field(self, field_name, model_field):
        from django.db.models import DecimalField as ModelDecimal

        if isinstance(model_field, ModelDecimal) and model_field.decimal_places == 3:
            kwargs = {"required": False, "allow_null": model_field.null}
            return MoneyField, kwargs
        return super().build_standard_field(field_name, model_field)


class CompanyScopedUidField(serializers.Field):
    """A company-owned lookup (department, shift, ...) addressed by uid.

    Output `{uid, title}`; input the uid or null. A uid from another company
    is refused as unknown.
    """

    def __init__(self, model, **kwargs):
        self.model = model
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def to_representation(self, value):
        out = {"uid": str(value.uid), "title": value.title}
        if getattr(value, "code", None):
            out["code"] = value.code
        return out

    def to_internal_value(self, data):
        company = self.context["company"]
        found = self.model.objects.filter(company=company, uid=data).first() if data else None
        if found is None:
            raise serializers.ValidationError("Not found in this company.")
        return found


class ManagerField(serializers.Field):
    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return {"code": value.code, "nameEn": value.name_en}

    def to_internal_value(self, data):
        found = Employee.objects.filter(company=self.context["company"], code=data).first() if data else None
        if found is None:
            raise serializers.ValidationError("No employee with that code in this company.")
        return found


# ------------------------------------------------------------------ employee

PERSONAL_FIELDS = [
    "name_en", "name_bn", "father_name", "mother_name", "marital", "spouse_name", "dob", "gender",
    "blood", "religion", "nid", "birth_cert", "passport", "work_permit", "mobile", "email",
    "present_address", "present_division", "permanent_same", "permanent_address", "permanent_division",
    "emergency_name", "emergency_relation", "emergency_phone", "photo",
]
EMPLOYMENT_FIELDS = [
    "classification", "worker_category", "establishment", "employment_type", "contract_end", "doj",
    "probation_end", "confirmation", "department", "section", "designation", "grade", "shift",
    "manager", "appointment_letter", "id_card", "id_card_date",
]
# Tracked on change (doc §8): field -> how to label a value in the timeline.
TRACKED = {
    "classification": lambda v: dict(ClassificationChoices.choices).get(v, v or ""),
    "designation": lambda v: v.title if v else "",
    "grade": lambda v: v or "",
    "department": lambda v: v.title if v else "",
    "shift": lambda v: (v.code or v.title) if v else "",
    "section": lambda v: v.title if v else "",
}


class PersonalSerializer(CamelModelSerializer):
    class Meta:
        model = Employee
        fields = PERSONAL_FIELDS

    def validate_name_en(self, value):
        if not (value or "").strip():
            raise serializers.ValidationError("A name in English is required — it prints on the service book.")
        return value.strip()

    def validate_nid(self, value):
        try:
            validation.validate_nid(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None
        return value

    def validate_mobile(self, value):
        try:
            validation.validate_mobile(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None
        return value

    def validate_emergency_phone(self, value):
        try:
            validation.validate_mobile(value, "Emergency phone")
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None
        return value

    def validate(self, attrs):
        # When permanent mirrors present, it is stored mirrored (§2.1).
        instance = self.instance
        same = attrs.get("permanent_same", instance.permanent_same if instance else False)
        if same:
            attrs["permanent_address"] = attrs.get("present_address", instance.present_address if instance else "")
            attrs["permanent_division"] = attrs.get("present_division", instance.present_division if instance else "")
        return attrs


class EmploymentSerializer(CamelModelSerializer):
    department = CompanyScopedUidField(CompanyDepartment)
    section = CompanyScopedUidField(CompanySection)
    designation = CompanyScopedUidField(CompanyDesignation)
    shift = CompanyScopedUidField(CompanyShift)
    manager = ManagerField()

    class Meta:
        model = Employee
        fields = EMPLOYMENT_FIELDS

    def validate(self, attrs):
        instance = self.instance
        # §6.1: changing an existing classification is a gated operation
        # (reason + effective date + audit). That endpoint is Phase 2; until it
        # exists, the first assignment is allowed and a change is refused.
        new = attrs.get("classification")
        if instance and new is not None and instance.classification and new != instance.classification:
            raise serializers.ValidationError({
                "classification": "Changing a classification is a gated operation (reason and effective "
                "date required, doc §6.1) and is not available yet."
            })
        if "manager" in attrs and instance and attrs["manager"] and attrs["manager"].pk == instance.pk:
            raise serializers.ValidationError({"manager": "An employee cannot manage themself."})
        employment_type = attrs.get("employment_type", instance.employment_type if instance else "")
        contract_end = attrs.get("contract_end", instance.contract_end if instance else None)
        if employment_type == "CONTRACT" and not contract_end:
            raise serializers.ValidationError({"contract_end": "A contract end date is required for a contract."})
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        request = self.context["request"]
        before = {f: getattr(instance, f) for f in TRACKED if f in validated_data}
        instance = super().update(instance, validated_data)
        for field_name, old in before.items():
            new = getattr(instance, field_name)
            if new != old:
                label = TRACKED[field_name]
                EmployeeFieldHistory.objects.create(
                    employee=instance,
                    field=TrackedFieldChoices(field_name),
                    date=clock.today(),
                    from_value=label(old),
                    to_value=label(new),
                    by=request.user,
                    by_name=getattr(request.user, "name", "") or getattr(request.user, "email", ""),
                )
        return instance


class EmployeeCreateSerializer(serializers.Serializer):
    """Minimal create (§9): `nameEn` is required, everything else may follow."""

    code = serializers.CharField(required=False, allow_blank=False, max_length=20)
    nameEn = serializers.CharField(allow_blank=True)
    nameBn = serializers.CharField(required=False, allow_blank=True, default="")
    mobile = serializers.CharField(required=False, allow_blank=True, default="")
    classification = serializers.ChoiceField(ClassificationChoices.choices, required=False, allow_blank=True, default="")
    workerCategory = serializers.ChoiceField(
        Employee._meta.get_field("worker_category").choices, required=False, allow_blank=True, default="")
    establishment = serializers.ChoiceField(
        Employee._meta.get_field("establishment").choices, required=False, allow_blank=True, default="")
    doj = serializers.DateField(required=False, allow_null=True, default=None)

    def validate_nameEn(self, value):
        if not value.strip():
            raise serializers.ValidationError("A name in English is required — it prints on the service book.")
        return value.strip()

    def validate_mobile(self, value):
        try:
            validation.validate_mobile(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None
        return value

    def validate_code(self, value):
        if Employee.objects.filter(company=self.context["company"], code=value).exists():
            raise serializers.ValidationError("That code is already in use. A code is never reassigned.")
        return value

    def create(self, validated_data):
        from employeeio.services.profile import next_code

        company = self.context["company"]
        return Employee.objects.create(
            company=company,
            code=validated_data.get("code") or next_code(company),
            name_en=validated_data["nameEn"],
            name_bn=validated_data["nameBn"],
            mobile=validated_data["mobile"],
            classification=validated_data["classification"],
            worker_category=validated_data["workerCategory"],
            establishment=validated_data["establishment"],
            doj=validated_data["doj"],
        )


# --------------------------------------------------------------- sub-records


class StatutorySerializer(CamelModelSerializer):
    pf_constituted = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeStatutory
        fields = [
            "pf_member", "pf_constituted", "pf_number", "pf_enrolled", "pf_employee", "pf_employer",
            "gratuity_eligible", "gratuity_basis", "gratuity_method", "gratuity_fund",
            "insurance_covered", "insurance_policy", "insurance_sum", "insurer",
            "festival_granted", "festival_reason",
        ]

    def get_pf_constituted(self, obj):
        profile = CompanyStatutoryProfile.objects.filter(company_id=obj.employee.company_id).first()
        return bool(profile and profile.pf_constituted)

    def _percent(self, value):
        if value is None:
            return value
        try:
            return validation.validate_pf_percent(value, rule_book(clock.today()))
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None

    def validate_pf_employee(self, value):
        return self._percent(value)

    def validate_pf_employer(self, value):
        return self._percent(value)

    def validate(self, attrs):
        instance = self.instance
        if attrs.get("pf_member") and not (instance and self.get_pf_constituted(instance)):
            raise serializers.ValidationError({
                "pf_member": "No provident fund is constituted for this company, so membership cannot be switched on."
            })
        granted = attrs.get("festival_granted", instance.festival_granted if instance else False)
        reason = attrs.get("festival_reason", instance.festival_reason if instance else "")
        if granted and self._before_eligibility(instance) and not (reason or "").strip():
            raise serializers.ValidationError({
                "festival_reason": "Granting a festival bonus before eligibility needs a reason."
            })
        return attrs

    def _before_eligibility(self, instance):
        from employeeio.services.profile import service_parts

        employee = instance.employee
        if not employee.doj:
            return True
        months = rule_book(clock.today()).labour.value("festivalBonusServiceMonths")
        return service_parts(employee.doj, clock.today()).total_months < months


class TaxProfileSerializer(CamelModelSerializer):
    class Meta:
        model = EmployeeTaxProfile
        fields = [
            "category", "disabled_children", "etin", "psr", "psr_date", "vehicle", "accommodation",
            "accommodation_value", "prior_employer", "prior_name", "prior_income", "prior_tds",
            "tax_borne_by_employer",
        ]

    def validate(self, attrs):
        instance = self.instance
        employee = instance.employee
        category = attrs.get("category", instance.category)
        if category == "NON_RESIDENT_FOREIGN" and not employee.work_permit:
            raise serializers.ValidationError({
                "category": "A non-resident foreign employee needs a work permit on the Personal tab."
            })
        return attrs


class PaymentSerializer(CamelModelSerializer):
    class Meta:
        model = EmployeePaymentProfile
        fields = [
            "method", "cash_reason", "bank", "branch", "routing", "account_name", "account_number",
            "account_type", "mfs_provider", "wallet_number", "wallet_type", "on_hold", "hold_reason",
            "hold_approver", "hold_since",
        ]

    def validate(self, attrs):
        instance = self.instance
        get = lambda f: attrs.get(f, getattr(instance, f))  # noqa: E731
        method = get("method")
        if method == PaymentMethodChoices.CASH and not (get("cash_reason") or "").strip():
            raise serializers.ValidationError({
                "cash_reason": "Record why this employee is paid in cash. Cash wages are lawful, but "
                "the salary is disallowed to the employer as a deduction (Income Tax Act 2023, s.55)."
            })
        if method == PaymentMethodChoices.MFS and not validation.mobile_valid(get("wallet_number")):
            raise serializers.ValidationError({"wallet_number": "Wallet number must be 11 digits starting 01."})
        return attrs


class NomineeSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    relation = serializers.ChoiceField(EmployeeNominee._meta.get_field("relation").choices, allow_blank=True, default="")
    nid = serializers.CharField(max_length=32, allow_blank=True, default="")
    share = serializers.DecimalField(max_digits=7, decimal_places=3)

    def to_internal_value(self, data):
        if isinstance(data, dict) and isinstance(data.get("share"), float):
            raise serializers.ValidationError({"share": "Send the share as a decimal string."})
        return super().to_internal_value(data)

    def validate_nid(self, value):
        try:
            validation.validate_nid(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None
        return value


class NomineeListSerializer(serializers.Serializer):
    nominees = NomineeSerializer(many=True)

    def validate_nominees(self, value):
        if value:
            total = sum((n["share"] for n in value), Decimal("0"))
            if abs(total - Decimal("100")) > Decimal("0.001"):
                raise serializers.ValidationError(
                    f"Nominee shares total {format(total.normalize(), 'f')}%; they must total 100%."
                )
        return value


def nominee_out(n):
    return {"uid": str(n.uid), "name": n.name, "relation": n.relation, "nid": n.nid,
            "share": format(n.share.normalize(), "f")}


class InvestmentSerializer(serializers.Serializer):
    instrument = serializers.ChoiceField(EmployeeInvestment._meta.get_field("instrument").choices)
    amount = MoneyField(min_value=Decimal("0"))
    proof = serializers.BooleanField(default=False)


class InvestmentListSerializer(serializers.Serializer):
    investments = InvestmentSerializer(many=True)


def investment_out(i):
    return {"uid": str(i.uid), "instrument": i.instrument, "amount": money_str(i.amount), "proof": i.proof}


def history_out(h):
    return {
        "uid": str(h.uid), "field": h.field, "date": h.date.isoformat(), "from": h.from_value,
        "to": h.to_value, "by": h.by_name, "reason": h.reason,
    }


def structure_out(structure):
    if structure is None:
        return None
    return {
        "uid": str(structure.uid),
        "effectiveFrom": structure.effective_from.isoformat(),
        "effectiveTo": structure.effective_to.isoformat() if structure.effective_to else None,
        "template": structure.template,
        "gross": money_str(structure.gross),
        "components": [
            {"code": c.code, "amount": money_str(c.amount)} for c in structure.components.all()
        ],
    }


# ------------------------------------------------------------------ profile


class EmployeeProfileSerializer(serializers.Serializer):
    """The full profile (GET /employees/{code}). Every sub-record is read fresh
    for this employee -- replaced, never merged (§1.3)."""

    def to_representation(self, employee):
        from employeeio.services.profile import service_parts
        from employeeio.services.salary import structure_in_force
        from employeeio.services.tax import suggest_category

        context = self.context
        today = clock.today()
        personal = PersonalSerializer(employee, context=context).data
        employment = EmploymentSerializer(employee, context=context).data
        service = service_parts(employee.doj, today) if employee.doj else None
        return {
            "code": employee.code,
            "uid": str(employee.uid),
            "status": employee.status,
            "asOf": today.isoformat(),
            "personal": personal,
            "employment": {
                **employment,
                "completedPayrollRuns": employee.completed_payroll_runs,
                "separatedOn": employee.separated_on.isoformat() if employee.separated_on else None,
                "separationType": employee.separation_type,
                "finalSettlementOn": employee.final_settlement_on.isoformat() if employee.final_settlement_on else None,
                "service": service.as_dict() if service else None,
            },
            "nominees": [nominee_out(n) for n in employee.nominees.all()],
            "statutory": StatutorySerializer(employee.statutory, context=context).data,
            "taxProfile": {
                **TaxProfileSerializer(employee.tax_profile, context=context).data,
                "categorySuggestion": suggest_category(employee, today),
            },
            "investments": [investment_out(i) for i in employee.investments.all()],
            "payment": PaymentSerializer(employee.payment, context=context).data,
            "salary": structure_out(structure_in_force(employee, today)),
            "history": [history_out(h) for h in employee.field_history.all()],
        }


class EmployeeRosterSerializer(serializers.Serializer):
    """One roster row (§9). `blockerCount` is the profile's hard-block count --
    the same `evaluate()` call, never a second implementation."""

    def to_representation(self, employee):
        from employeeio.services.compliance import evaluate
        from employeeio.services.salary import structure_in_force

        today = clock.today()
        structure = structure_in_force(employee, today)
        result = self.context.get("compliance", {}).get(employee.pk) or evaluate(employee, as_of=today)
        return {
            "code": employee.code,
            "nameEn": employee.name_en,
            "nameBn": employee.name_bn,
            "designation": employee.designation.title if employee.designation else None,
            "department": employee.department.title if employee.department else None,
            "workerCategory": employee.worker_category,
            "classification": employee.classification,
            "dateOfJoining": employee.doj.isoformat() if employee.doj else None,
            "grossMonthly": money_str(structure.gross) if structure else None,
            "blockerCount": len(result.blocks),
            "fresh": employee.created_at.date() == today,
        }


__all__ = [
    "EmployeeCreateSerializer", "EmployeeProfileSerializer", "EmployeeRosterSerializer",
    "EmploymentSerializer", "InvestmentListSerializer", "NomineeListSerializer", "PaymentSerializer",
    "PersonalSerializer", "StatutorySerializer", "TaxProfileSerializer", "history_out",
    "investment_out", "nominee_out", "structure_out", "ui_errors",
]
