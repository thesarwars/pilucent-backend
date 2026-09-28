"""Does this company own the TaxBandits record it is asking about?

Every call to TaxBandits authenticates with `get_access_token()`, which mints a
JWT from settings -- **one service credential for the whole platform**
(`utils.py:31-46`). Upstream therefore cannot tell our tenants apart. Any
`SubmissionId` or `RecordId` that reaches it is fetched, and any payload that
reaches Transmit is filed with the IRS. The only place tenancy can be enforced
is here, before the call.

The list and create views already did this inline, resolving the company's own
`TaxBanditsBusinessAccount` first. The fetch-by-external-id views did not, which
is what these helpers close.

Ownership is checked **per form type**. A 940 submission id must not authorise a
941 call: the ids come from the same upstream namespace and nothing else would
stop one standing in for the other.
"""

from taxbanditsio.models import (
    TaxBanditsBusinessAccount,
    TaxBanditsReturn940,
    TaxBanditsReturn941,
)


def _owns(model, company, *, submission_id=None, record_id=None):
    if company is None:
        return False
    filters = {"company": company}
    if submission_id:
        filters["submission_id"] = submission_id
    if record_id:
        filters["record_id"] = record_id
    if len(filters) == 1:  # nothing to match on but the company
        return False
    return model.objects.filter(**filters).exists()


def owns_940(company, submission_id=None, record_id=None):
    """True when this company filed the Form 940 identified upstream."""
    return _owns(
        TaxBanditsReturn940, company, submission_id=submission_id, record_id=record_id
    )


def owns_941(company, submission_id=None, record_id=None):
    """True when this company filed the Form 941 identified upstream."""
    return _owns(
        TaxBanditsReturn941, company, submission_id=submission_id, record_id=record_id
    )


def owns_any_return(company, submission_id=None, record_id=None):
    """For endpoints that are not form-specific, e.g. the 8453-EMP signature."""
    return owns_940(company, submission_id, record_id) or owns_941(
        company, submission_id, record_id
    )


def company_business_ids(company):
    """The upstream business ids this company owns, for filtering a listing."""
    if company is None:
        return set()
    return set(
        TaxBanditsBusinessAccount.objects.filter(company=company)
        .exclude(tb_business_id__isnull=True)
        .exclude(tb_business_id="")
        .values_list("tb_business_id", flat=True)
    )


def extract_submission_id(payload):
    """Find a SubmissionId anywhere in a Transmit payload, or None.

    Searched recursively and case-insensitively because the upstream contract is
    not pinned on our side, and the webhook handlers already accept both
    `SubmissionId` and `SubmissionID` (`weapi/.../taxbandits/webhooks.py:17`).

    Returning None means the caller cannot prove what it is transmitting, and
    the view refuses -- transmitting an unidentifiable payload under the
    platform credential is the exact risk this guards.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.replace("_", "").lower() == "submissionid" and value:
                return str(value)
        for value in payload.values():
            found = extract_submission_id(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = extract_submission_id(item)
            if found:
                return found
    return None
