"""Narrow a serializer's related-field querysets to the requesting company.

DRF builds related fields once, at class-definition time, so their querysets
cannot mention the request -- which is why every one of them in this codebase
was global. The `parent_uid` field on a chart of account accepted any account in
the database, including another tenant's and including soft-deleted ones; the
product serializers' account, brand, category and supplier fields did the same.

RLS does not close this. The policy is deliberately permissive when
`app.company_id` is unset, and these lookups run inside an ordinary tenant
request anyway -- the row resolves, the FK validates, and the write succeeds
pointing at somebody else's data.
"""

from django.db.models import Q

from categoryio.models import Category


def company_scoped(queryset, serializer):
    """Narrow one related-field queryset to the serializer's active company.

    Returns the queryset untouched when there is no request to scope by (schema
    generation, shell use, internal calls), and empty when there is a user but
    no active company -- a request that cannot name a tenant must not reach one.

    The category taxonomy is seeded globally with `company` NULL and is *also*
    tenant-writable, so those fields have to admit both the shared rows and the
    caller's own. Filtering them to the company alone would reject every
    built-in account type.
    """
    request = serializer.context.get("request") if serializer.context else None
    user = getattr(request, "user", None)
    if user is None or not hasattr(user, "get_active_company"):
        return queryset

    company = user.get_active_company()
    if company is None:
        return queryset.none()

    model_fields = {f.name for f in queryset.model._meta.get_fields()}
    if "company" not in model_fields:
        return queryset

    if queryset.model is Category:
        return queryset.filter(Q(company__isnull=True) | Q(company=company))
    return queryset.filter(company=company)


class CompanyScopedRelatedFieldsMixin:
    """Apply `company_scoped` to every writable related field on a serializer.

    Applied in `get_fields`, not at class level, because the queryset has to
    resolve per request. Mix in ahead of ModelSerializer.

    **In `get_fields` and not `__init__`, and that is the whole of BR-25.**

    `__init__` runs when the serializer is *constructed*. For a top-level
    serializer that is the moment the view builds it, with the request already
    in `context`, so scoping worked. For a NESTED one it is class-definition
    time:

        class TransactionRuleCreateSerializer(Serializer):
            assign = TransactionRuleAssignSerializer(required=False)

    That inner serializer is instantiated once, when the module is imported,
    when there is no request and no company. `company_scoped` correctly returned
    the queryset untouched -- and then nothing ever narrowed it again, so the
    mixin was inert on exactly the serializer that needed it, while looking
    present in the class declaration.

    `get_fields` is called lazily, on first access to `.fields`, by which time
    DRF's `context` property resolves through `self.root` to the request. So the
    nested case is scoped and the top-level case is unchanged.

    The same shape as `.fields` versus `get_fields()` elsewhere in this codebase:
    something is computed once, somewhere that cannot see the request.
    """

    def get_fields(self):
        fields = super().get_fields()
        for field in fields.values():
            queryset = getattr(field, "queryset", None)
            if queryset is not None:
                field.queryset = company_scoped(queryset, self)
        return fields
