"""Employee documents (doc §9): the service book, appointment letter and ID card.

Templates are data, never markup (the front end's `docs.js`): a document is
the filled template, frozen when it is issued, and the client renders it. A
reissue is a new version; the copy the employee holds can always be shown again.

Every amount carries its words in English and Bangla (§10), and every salary
component its **effective** share of gross, back-solved from the amounts on
file -- never the template's percentage (§5.1).
"""

from django.db import transaction
from django.db.models import Max

from common import clock
from common.words import both_words, format_date, format_money
from rulebookio.book import UnknownRule, rule_book

from ..choices import (
    BloodGroupChoices,
    ClassificationChoices,
    DocumentKindChoices,
    EmploymentTypeChoices,
    WorkerCategoryChoices,
)
from ..models import Employee, EmployeeDocument
from ..ui import FIELD_IDS
from .salary import components_out, latest_structure, structure_in_force
from .validation import nid_valid

K = DocumentKindChoices
TITLES = {
    K.SERVICE_BOOK: ("Service book", "সার্ভিস বই"),
    K.APPOINTMENT_LETTER: ("Appointment letter", "নিয়োগপত্র"),
    K.ID_CARD: ("Identity card", "পরিচয়পত্র"),
}
CITATION_KEYS = {K.SERVICE_BOOK: "serviceBook", K.APPOINTMENT_LETTER: "appointmentLetter", K.ID_CARD: "idCard"}


class DocumentRefused(Exception):
    def __init__(self, missing):
        self.missing = missing  # [(field, message)]
        super().__init__("; ".join(m for _, m in missing))

    def as_errors(self):
        return {"errors": [{"field": FIELD_IDS.get(f, f), "path": f, "messages": [m]} for f, m in self.missing]}


def _actor(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def missing_for(employee, kind, on=None):
    """What stops `kind` being issued, as (field, message) pairs."""
    on = on or clock.today()
    missing = []
    if kind == K.SERVICE_BOOK:
        if not employee.father_name:
            missing.append(("father_name", "Father's name is required on the service book."))
        if not employee.mother_name:
            missing.append(("mother_name", "Mother's name is required on the service book."))
        if not nid_valid(employee.nid):
            missing.append(("nid", "A valid National ID (10, 13 or 17 digits) is required on the service book."))
        if not employee.permanent_address:
            missing.append(("permanent_address", "The permanent address appears on the service book."))
        if not employee.doj:
            missing.append(("doj", "The date of joining is required on the service book."))
    elif kind == K.APPOINTMENT_LETTER:
        if not employee.doj:
            missing.append(("doj", "The appointment letter states the date of joining."))
        if not employee.designation_id:
            missing.append(("designation", "The appointment letter states the designation."))
        if latest_structure(employee) is None:
            missing.append(("salary", "The appointment letter states the wage: assign a salary structure first."))
    elif kind == K.ID_CARD:
        if not employee.photo:
            missing.append(("photo", "The ID card carries the employee's photograph."))
        if not employee.designation_id:
            missing.append(("designation", "The ID card states the designation."))
    return missing


def _money(amount):
    return {"amount": str(amount), "display": {"en": format_money(amount), "bn": format_money(amount, "bn")},
            "words": both_words(amount)}


def _dates(value):
    return {"iso": value.isoformat() if value else None,
            "display": {"en": format_date(value), "bn": format_date(value, "bn")}}


def _employer(company):
    return {"name": company.legal_name or company.name, "address": company.customer_facing_address or ""}


def _identity(e):
    return {
        "code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn, "fatherName": e.father_name,
        "motherName": e.mother_name, "spouseName": e.spouse_name, "dob": _dates(e.dob), "nid": e.nid,
        "gender": e.gender, "blood": dict(BloodGroupChoices.choices).get(e.blood, e.blood) if e.blood else "",
        "presentAddress": e.present_address, "permanentAddress": e.permanent_address, "mobile": e.mobile,
        "photo": e.photo.url if e.photo else None,
    }


def _employment(e):
    return {
        "designation": e.designation.title if e.designation_id else "",
        "department": e.department.title if e.department_id else "",
        "section": e.section.title if e.section_id else "",
        "grade": e.grade,
        "classification": dict(ClassificationChoices.choices).get(e.classification, ""),
        "workerCategory": dict(WorkerCategoryChoices.choices).get(e.worker_category, ""),
        "employmentType": dict(EmploymentTypeChoices.choices).get(e.employment_type, ""),
        "doj": _dates(e.doj), "probationEnd": _dates(e.probation_end), "confirmation": _dates(e.confirmation),
        "contractEnd": _dates(e.contract_end),
    }


def _wage(structure):
    if structure is None:
        return None
    components = [(c.code, c.amount) for c in structure.components.all()]
    gross = structure.gross
    return {
        "effectiveFrom": _dates(structure.effective_from),
        "gross": _money(gross),
        "components": [{**row, "words": both_words(amount)}
                       for row, (_, amount) in zip(components_out(components, gross), components)],
    }


def _citation(book, kind):
    try:
        return book.labour.citation(CITATION_KEYS[kind])
    except UnknownRule:
        return None


def build_content(employee, kind, on=None):
    on = on or clock.today()
    book = rule_book(on)
    title_en, title_bn = TITLES[kind]
    content = {
        "template": kind, "titleEn": title_en, "titleBn": title_bn,
        # docs.js: the statutory layouts are unverified against the gazette forms.
        "verified": False,
        "citation": _citation(book, kind),
        "issuedOn": _dates(on),
        "employer": _employer(employee.company),
        "employee": _identity(employee),
    }
    if kind == K.SERVICE_BOOK:
        structure = structure_in_force(employee, on) or latest_structure(employee)
        content["employment"] = _employment(employee)
        content["wage"] = _wage(structure)
        # Every recorded change, oldest first: the book is read as a career.
        content["entries"] = [
            {"serial": n, "particular": h.get_field_display(), "effectiveFrom": _dates(h.date),
             "from": h.from_value, "to": h.to_value, "reason": h.reason, "authorisedBy": h.by_name}
            for n, h in enumerate(employee.field_history.order_by("date", "created_at", "id"), 1)
        ]
    elif kind == K.APPOINTMENT_LETTER:
        structure = structure_in_force(employee, employee.doj or on) or latest_structure(employee)
        content["employment"] = _employment(employee)
        content["wage"] = _wage(structure)
        notice = book.labour.get("noticePeriodDaysByWorkerCategory")
        days = notice.value.get(employee.worker_category)
        content["noticeDays"] = (
            {"value": days, "citation": notice.citation, "confidence": notice.confidence} if days is not None else None
        )
    else:
        content["employment"] = {k: v for k, v in _employment(employee).items()
                                 if k in ("designation", "department", "doj")}
        content["emergency"] = {"name": employee.emergency_name, "phone": employee.emergency_phone}
    return content


def issue(employee, kind, user=None):
    """Issue (or reissue) `kind`, frozen. Issuing the appointment letter or
    the ID card sets the employee's flag; the service book clears its risk."""
    missing = missing_for(employee, kind)
    if missing:
        raise DocumentRefused(missing)
    today = clock.today()
    with transaction.atomic():
        locked = Employee.objects.select_for_update().get(pk=employee.pk)
        version = (EmployeeDocument.objects.filter(employee=locked, kind=kind)
                   .aggregate(v=Max("version"))["v"] or 0) + 1
        document = EmployeeDocument.objects.create(
            employee=locked, kind=kind, version=version, issued_on=today, issued_by=user,
            issued_by_name=_actor(user), content=build_content(employee, kind, today),
        )
        if kind == K.APPOINTMENT_LETTER and not locked.appointment_letter:
            locked.appointment_letter = True
            locked.save(update_fields=["appointment_letter", "updated_at"])
            employee.appointment_letter = True
        elif kind == K.ID_CARD:
            locked.id_card, locked.id_card_date = True, today
            locked.save(update_fields=["id_card", "id_card_date", "updated_at"])
            employee.id_card, employee.id_card_date = True, today
    return document


def document_out(document, content=True):
    out = {
        "uid": str(document.uid), "kind": document.kind, "version": document.version,
        "issuedOn": document.issued_on.isoformat(), "issuedBy": document.issued_by_name,
    }
    if content:
        out["content"] = document.content
    return out


def documents_out(employee):
    documents = list(EmployeeDocument.objects.filter(employee=employee).order_by("kind", "-version"))
    kinds = []
    for kind in K:
        issued = [d for d in documents if d.kind == kind]
        missing = missing_for(employee, kind)
        kinds.append({
            "kind": kind.value, "label": kind.label, "issued": bool(issued),
            "latest": document_out(issued[0], content=False) if issued else None,
            "ready": not missing,
            "missing": [{"field": FIELD_IDS.get(f, f), "path": f, "message": m} for f, m in missing],
        })
    return {"kinds": kinds, "documents": [document_out(d) for d in documents]}
