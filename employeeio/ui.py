"""The Employee Profile BD front end's input ids.

Compliance findings route to these, and API validation errors are addressed by
them, so the client can open the right tab and focus the offending input
(doc §3.3, §9). They are the front end's own ids -- a renamed one is a finding
that navigates nowhere.
"""

# snake_case model field -> UI input id.
FIELD_IDS = {
    "code": "f-code", "name_en": "f-nameEn", "name_bn": "f-nameBn", "father_name": "f-fatherName",
    "mother_name": "f-motherName", "marital": "f-marital", "spouse_name": "f-spouse", "dob": "f-dob",
    "gender": "f-gender", "blood": "f-blood", "religion": "f-religion", "nid": "f-nid",
    "birth_cert": "f-birthCert", "passport": "f-passport", "mobile": "f-mobile", "email": "f-email",
    "present_address": "f-presAddr", "present_division": "f-presDiv", "permanent_same": "f-permSame",
    "permanent_address": "f-permAddr", "permanent_division": "f-permDiv", "emergency_name": "f-emgName",
    "emergency_relation": "f-emgRel", "emergency_phone": "f-emgPhone", "photo": "f-photo",
    "worker_category": "f-category", "establishment": "f-establishment", "employment_type": "f-empType",
    "doj": "f-doj", "probation_end": "f-probation", "confirmation": "f-confirmation",
    "department": "f-department", "section": "f-section", "designation": "f-designation",
    "grade": "f-grade", "shift": "f-shift", "manager": "f-manager", "appointment_letter": "f-appointment",
    "id_card": "f-idcard",
    "pf_number": "f-pfnum", "pf_enrolled": "f-pfdate", "pf_employee": "f-pfemp", "pf_employer": "f-pfer",
    "gratuity_basis": "f-gratbasis", "gratuity_method": "f-gratmethod", "gratuity_fund": "f-gratfund",
    "insurance_policy": "f-inspolicy", "insurance_sum": "f-inssum", "insurer": "f-insurer",
    "festival_reason": "f-festreason",
    "category": "f-taxcat", "disabled_children": "f-disabledkids", "etin": "f-etin", "psr": "f-psr",
    "vehicle": "f-vehicle", "accommodation": "f-accom", "accommodation_value": "f-accomval",
    "prior_employer": "f-prior", "prior_name": "f-priorname", "prior_income": "f-priorinc",
    "tax_borne_by_employer": "f-borne",
    "cash_reason": "f-cashreason", "bank": "f-bank", "branch": "f-branch", "routing": "f-routing",
    "account_name": "f-accname", "account_number": "f-accnum", "account_type": "f-acctype",
    "mfs_provider": "f-mfsprov", "wallet_number": "f-wallet", "wallet_type": "f-wallettype",
    "hold_reason": "f-holdreason", "hold_approver": "f-holdapprover",
    "nominees": "f-nominee",
}
