"""Resolve which company a billing/subscription action targets.

With multi-company accounts, an owner can hold a separate subscription per
company. A billing request must therefore be tied to a *specific* company, not
silently defaulted to the user's first membership.

This resolver prefers an explicit ``company_uid`` in the request body (validated
to be one of the requesting user's companies), so the client can pay for a
specific company regardless of the token's scope. When omitted it falls back to
the active company (the scoped token's company), preserving the original
single-company behaviour.
"""

from rest_framework.serializers import ValidationError


def resolve_billing_company(request):
    company_uid = request.data.get("company_uid") if hasattr(request, "data") else None
    user = request.user

    if company_uid:
        company_user = (
            user.companyuser_set.select_related("company")
            .filter(company__uid=company_uid)
            .first()
        )
        if company_user is None:
            raise ValidationError(
                {"company_uid": "You do not have access to this company."}
            )
        return company_user.company

    return user.get_active_company()
