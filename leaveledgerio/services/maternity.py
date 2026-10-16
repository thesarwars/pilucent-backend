"""Maternity (backend spec §3.10; the Leave Operations design's maternity
tab): the case, the benefit, the statutory sequence and the protection.

A benefit computation is not a process. The statute imposes an order --
notice, proof of pregnancy and the first instalment, delivery, proof of
birth and the second instalment, the employment ban, the return -- and
every due date derives from a few recorded dates. `schedule()` is the one
definition of "when is this due", read by the register, the timeline and
the overdue test alike.

Three positions:
- The leave is an entitlement; the benefit is conditional. A failed benefit
  condition removes the money, never the leave.
- The benefit basis is disputed (s.48: 3 months' wages ÷ days actually
  worked; Rules 2022: 1 month ÷ 26), so it is an election made on the
  record, computed both ways before it is made.
- Employing a woman within the ban after delivery is prohibited outright:
  the one transition that refuses rather than warns.
"""

import calendar as pycal
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from common import clock
from common.money import money_str, round_to_paisa

from ..choices import (
    BenefitBasisChoices,
    CycleKindChoices as CK,
    LeaveAuditActionChoices as A,
    LeaveEventChoices as E,
    LedgerReasonChoices as R,
    MaternityEventChoices as M,
    RequestStatusChoices as S,
)
from ..models import RESTRICTED_MATERNITY_FIELDS, LeaveCycle, LeaveRequest, MaternityCase, MaternityEvent
from .core import (
    ZERO,
    Book,
    LeaveRefused,
    actor_name,
    add_months,
    audit,
    d4,
    day_breakdown,
    ensure_types,
    fmt,
    months_between,
    plural,
    post,
    restriction,
)
from .events import emit

OPEN = ("NOTIFIED", "ON_LEAVE_PRE", "DELIVERED", "ON_LEAVE_POST")


def _who(user):
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _date(value, field):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise LeaveRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}, status=400) from None


# ==================================================================== benefit


def _days_actually_worked(employee, start, end, book):
    """Days actually worked in [start, end] from attendance, when attendance
    has settled every employed day; otherwise the employed calendar days,
    said so."""
    from employeeio.services.sites import site_of
    from timekeepingio.services.engine import Rules
    from timekeepingio.services.window import Window

    first = max(start, employee.doj or start)
    last = min(end, employee.separated_on or end)
    if last < first:
        return Decimal(0), "not employed"
    calendar_days = Decimal((last - first).days + 1)
    try:
        rules = Rules.from_rule_set(book.rule_set(last))
        w = Window(employee.company, site_of(employee), [employee], first, last, rules, strict_calendar=False,
                   today=clock.today())
    except LeaveRefused:
        return calendar_days, "calendar days: no rule set for attendance"
    recs = w.records(employee)
    settled = all(r.status and r.status != "EXCEPTION" for r in recs) and not w.kinds.missing
    if not settled:
        return calendar_days, "calendar days: attendance not settled for the month"
    worked = sum((Decimal(1) if r.status in ("PRESENT", "PRESENT_OT", "ON_DUTY") else
                  Decimal("0.5") if r.status == "HALF_DAY" else Decimal(0)) for r in recs)
    return worked, "attendance"


def reference_lines(employee, notice, months, book):
    """The `months` whole months before the notice month: the wage in force
    at each month's end (salary structure gross -- the same source payroll
    uses) and the days actually worked."""
    from employeeio.services.salary import structure_in_force

    lines = []
    first_of_notice = notice.replace(day=1)
    for i in range(months, 0, -1):
        start = add_months(first_of_notice, -i)
        end = start.replace(day=pycal.monthrange(start.year, start.month)[1])
        structure = structure_in_force(employee, end)
        days, source = _days_actually_worked(employee, start, end, book)
        employed = (employee.doj is None or employee.doj <= end) and days > 0
        wage = d4(structure.gross) if structure is not None and employed else ZERO
        lines.append({"month": start.strftime("%Y-%m"), "label": start.strftime("%b %Y"), "wage": money_str(wage),
                      "days": str(days.normalize()) if days else "0", "daysSource": source,
                      "wageSource": "salary structure gross" if structure is not None else "no structure in force"})
    return lines


def compute_benefit(lines, basis, before, after):
    """Both bases from the same reference lines, so an election is made
    against the numbers it changes."""
    months = len(lines)
    total_wage = sum((Decimal(x["wage"]) for x in lines), ZERO)
    total_days = sum((Decimal(x["days"]) for x in lines), ZERO)
    days = before + after
    if basis == BenefitBasisChoices.RULES_2022:
        daily = (total_wage / months / 26) if months else ZERO
        text = (f"৳{money_str(total_wage)} over {months} months ÷ {months} = ৳{money_str(total_wage / months if months else 0)} "
                f"a month ÷ 26 = ৳{money_str(daily)} a day × {days} days")
    else:
        daily = (total_wage / total_days) if total_days else ZERO
        text = (f"৳{money_str(total_wage)} over {months} months ÷ {total_days.normalize()} days actually worked = "
                f"৳{money_str(daily)} a day × {days} days")
    daily = round_to_paisa(daily)
    benefit = round_to_paisa(daily * days)
    first = round_to_paisa(daily * before)
    return {"basis": basis, "totalWage": total_wage, "totalDays": total_days, "averageDailyWage": daily,
            "benefitDays": days, "benefit": benefit, "first": first, "second": benefit - first, "text": text}


def benefit_preview(company, employee, notice_date, *, figures):
    """For the case wizard: the reference months and the benefit on every
    basis the rule book offers on that date."""
    notice = _date(notice_date, "noticeDate")
    book = Book()
    rules = book.rules(notice)
    lines = reference_lines(employee, notice, rules.maternity_reference_months, book)
    out = []
    for key, opt in rules.maternity_basis_options.items():
        b = compute_benefit(lines, key, rules.maternity_before, rules.maternity_after)
        out.append({"key": key, "label": opt.get("label"), "citation": opt.get("citation"),
                    "isDefault": key == rules.maternity_basis,
                    "averageDailyWage": money_str(b["averageDailyWage"]) if figures else None,
                    "benefit": money_str(b["benefit"]) if figures else None, "text": b["text"] if figures else None})
    return {"lines": [{**x, "wage": x["wage"] if figures else None} for x in lines], "bases": out,
            "masked": not figures, "benefitDays": rules.maternity_before + rules.maternity_after,
            "confidence": next((r["confidence"] for r in rules.rows if r["key"] == "maternityBenefitBasis"), None)}


# =================================================================== schedule


def add_working_days(employee, start, n):
    """`n` working days after `start` on the site's published calendar.
    None, with the reason, when the calendar is not published: a deadline
    is not guessed (Friday is right for a factory and wrong for a shop)."""
    from employeeio.services.sites import site_of
    from timekeepingio.services.base import CalendarMissing, DayKinds

    site, years = site_of(employee), {}
    d, added = start, 0
    while added < n:
        d += timedelta(days=1)
        if d.year not in years:  # the next year's calendar only if the count reaches it
            try:
                years[d.year] = DayKinds(site, [d.year], strict=True)
            except CalendarMissing as exc:
                return None, exc.errors["calendar"][0]
        if years[d.year].of(d)[0] not in ("WEEKLY", "HOLIDAY"):
            added += 1
    return d, None


def schedule(case, rules):
    actual = case.actual_delivery
    basis_date = actual or case.expected_delivery
    pays = case.benefit_payable
    first_due, first_note = (add_working_days(case.employee, case.proof_of_pregnancy_on, rules.maternity_pay_working_days)
                             if pays and case.proof_of_pregnancy_on else (None, None))
    second_due, second_note = (add_working_days(case.employee, case.proof_of_birth_on, rules.maternity_pay_working_days)
                               if pays and case.proof_of_birth_on else (None, None))
    return {
        "leaveStart": case.pre_leave_from, "preNatalEnd": basis_date - timedelta(days=1),
        "postNatalEnd": case.post_leave_to, "expectedReturn": case.post_leave_to + timedelta(days=1),
        "deliveryIsEstimated": actual is None,
        "employmentBanEnd": case.employment_ban_end, "employmentBanWeeks": rules.maternity_ban_weeks,
        "proofOfBirthDue": add_months(actual, rules.maternity_proof_months) if actual else None,
        "proofOfBirthMonths": rules.maternity_proof_months, "paymentWorkingDays": rules.maternity_pay_working_days,
        "firstInstalmentDue": first_due, "secondInstalmentDue": second_due,
        "dueNote": first_note or second_note,
        "protectionFrom": case.protection_start, "protectionTo": case.protection_end,
    }


def next_action(case, sch, today):
    """What is owed now, and whether it is late. The register row and the
    case view read this same answer."""
    if case.status == "CANCELLED":
        return {"label": "Cancelled", "due": None, "overdue": False, "event": None}
    if case.status == "COMPLETED":
        return {"label": f"Closed — returned {fmt(case.returned_on)}", "due": None, "overdue": False, "event": None}
    if not case.proof_of_pregnancy_on:
        return {"label": "Awaiting proof of pregnancy", "due": None, "overdue": False, "event": M.PROOF_OF_PREGNANCY}
    if case.benefit_payable and not case.first_instalment_paid_on:
        due = sch["firstInstalmentDue"]
        return {"label": "First instalment due", "due": due, "overdue": bool(due and today > due), "event": M.PAY_FIRST}
    if not case.actual_delivery:
        # No due date: it would be the expected delivery, which is restricted.
        return {"label": "Awaiting delivery", "due": None,
                "overdue": today > case.expected_delivery + timedelta(days=14), "event": M.DELIVERY}
    if not case.proof_of_birth_on:
        due = sch["proofOfBirthDue"]
        return {"label": "Awaiting proof of birth", "due": due, "overdue": bool(due and today > due),
                "event": M.PROOF_OF_BIRTH}
    if case.benefit_payable and not case.second_instalment_paid_on:
        due = sch["secondInstalmentDue"]
        return {"label": "Second instalment due", "due": due, "overdue": bool(due and today > due),
                "event": M.PAY_SECOND}
    due = sch["expectedReturn"]
    return {"label": "On post-natal leave", "due": due, "overdue": today > due, "event": M.RETURN}


# ======================================================================= case


def open_case(company, employee, *, notice_date, notice_method, expected_delivery, surviving_children,
              basis=None, leave_from=None, user=None):
    """Recording the notice grants the leave: statutory, approved, not
    refusable. An oral notice on a past date is a valid notice. The benefit
    is worked out now, on the elected basis, and kept as worked out."""
    notice = _date(notice_date, "noticeDate")
    expected = _date(expected_delivery, "expectedDelivery")
    if notice_method not in ("WRITTEN", "ORAL"):
        raise LeaveRefused({"noticeMethod": ["WRITTEN or ORAL."]}, status=400)
    if expected <= notice:
        raise LeaveRefused({"expectedDelivery": ["The expected delivery falls after the notice."]}, status=400)
    try:
        children = int(surviving_children)
        if children < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise LeaveRefused({"survivingChildren": ["A count of surviving children, 0 or more."]}, status=400) from None
    ltype = ensure_types(company)["MATERNITY"]
    book = Book()
    rules = book.rules(notice)
    basis = basis or rules.maternity_basis
    if basis not in rules.maternity_basis_options:
        raise LeaveRefused({"basis": [f"The benefit basis is elected from those the rule book offers on {fmt(notice)}: "
                                      f"{', '.join(rules.maternity_basis_options)}."]}, status=400)
    why = restriction(employee, ltype, notice, rules, service=False)
    if why:
        raise LeaveRefused({"employee": [why]})
    if employee.doj is None:
        raise LeaveRefused({"employee": ["No date of joining recorded: service cannot be counted."]})
    before, after = rules.maternity_before, rules.maternity_after
    total = before + after
    start = _date(leave_from, "leaveFrom") if leave_from else expected - timedelta(days=before)
    if start > expected:
        raise LeaveRefused({"leaveFrom": ["The leave starts on or before the expected delivery."]})
    if start < expected - timedelta(days=before):
        raise LeaveRefused({"leaveFrom": [f"At most {before} days before the expected delivery."]})
    post_to = max(start + timedelta(days=total - 1), expected + timedelta(days=after - 1))
    served = months_between(employee.doj, notice)
    service_met = served >= rules.maternity_service_months
    children_met = children <= rules.maternity_max_children
    payable = service_met and children_met
    reasons = []
    if not service_met:
        reasons.append(f"{served} months' service at notice; the benefit needs {rules.maternity_service_months} "
                       f"({rules.citations['maternityMinimumServiceMonths']})")
    if not children_met:
        reasons.append(f"the surviving-children condition is not met ({rules.citations['maternityMaxSurvivingChildren']})")
    days = (post_to - start).days + 1
    reason = ("Benefit payable." if payable else "Benefit not payable: " + "; ".join(reasons) + ".") + \
        f" The {days} days of leave stand either way."
    lines = reference_lines(employee, notice, rules.maternity_reference_months, book)
    b = compute_benefit(lines, basis, before, after)
    protect = rules.maternity_protection
    with transaction.atomic():
        from employeeio.models import Employee

        Employee.objects.select_for_update().get(pk=employee.pk)
        if MaternityCase.objects.filter(employee=employee, status__in=OPEN).exists():
            raise LeaveRefused({"employee": [f"{employee.name_en} already has an open maternity case. Close it before "
                                             "opening another."]}, status=409)
        cycle = LeaveCycle.objects.create(company=company, employee=employee, leave_type=ltype, kind=CK.EVENT,
                                          starts_on=start, ends_on=post_to, rule_set=rules.rule_set)
        grant_entry = post(employee=employee, ltype=ltype, cycle=cycle, days=days, reason=R.ACCRUAL, effective=start,
                           user=user, rule_set=rules.rule_set,
                           basis=f"{plural(days, 'day')} of maternity leave, {before} before and {after} after the "
                                 f"delivery ({rules.citations['maternityDaysBefore']})")
        from .ops import _create_with_reference

        req = _create_with_reference(
            LeaveRequest, company, "LR", start.year, employee=employee, leave_type=ltype, cycle=cycle,
            from_date=start, to_date=post_to, days_consumed=grant_entry.days,
            day_breakdown=day_breakdown(employee, ltype, start, post_to), status=S.APPROVED, non_refusable=True,
            note="Maternity leave, granted on the notice.", created_by=_who(user), created_by_name=actor_name(user),
            decided_by=_who(user), decided_by_name=actor_name(user), decided_at=timezone.now())
        taken = post(employee=employee, ltype=ltype, cycle=cycle, days=-grant_entry.days, reason=R.TAKEN,
                     effective=start, user=user, source_ref=req.reference, rule_set=rules.rule_set,
                     basis=f"Maternity leave {fmt(start)} – {fmt(post_to)}: {plural(days, 'day')} ({req.reference})")
        req.ledger_entry = taken
        req.save(update_fields=["ledger_entry", "updated_at"])
        case = _create_with_reference(
            MaternityCase, company, "MAT", notice.year, employee=employee, notice_date=notice,
            notice_method=notice_method, notice_recorded_by=_who(user), notice_recorded_by_name=actor_name(user),
            expected_delivery=expected, surviving_children=children, service_months=served,
            service_months_met=service_met, children_met=children_met, benefit_payable=payable,
            eligibility_reason=reason, pre_leave_from=start, pre_leave_to=expected - timedelta(days=1),
            post_leave_from=expected, post_leave_to=post_to, total_days_granted=days,
            protection_start=add_months(notice, -int(protect.get("beforeMonths", 6))),
            protection_end=expected + timedelta(weeks=int(protect.get("afterWeeks", 8))),
            employment_ban_end=expected + timedelta(weeks=rules.maternity_ban_weeks),
            rule_set=rules.rule_set, request=req, benefit_basis=basis, basis_elected_by_name=actor_name(user),
            reference_lines=lines, total_wage=b["totalWage"], total_days=b["totalDays"],
            average_daily_wage=b["averageDailyWage"], benefit_days=b["benefitDays"],
            benefit_amount=b["benefit"] if payable else ZERO, first_instalment_amount=b["first"] if payable else ZERO,
            second_instalment_amount=b["second"] if payable else ZERO, benefit_basis_text=b["text"])
        _event(case, M.NOTICE, notice, user,
               f"{notice_method.lower()} notice · expected delivery recorded · "
               f"{'benefit payable' if payable else 'leave only, the benefit is not payable'}")
        audit(company, case, A.MATERNITY_OPENED, user, on_behalf_of=employee,
              after={"leave": [start.isoformat(), post_to.isoformat()], "benefitPayable": payable, "basis": basis,
                     "noticeMethod": notice_method}, rule_set=rules.rule_set)
        emit(company, E.MATERNITY_CASE_OPENED, employee=employee, entity_ref=case.reference, actor=user,
             payload={"leaveFrom": start.isoformat(), "leaveTo": post_to.isoformat(), "benefitPayable": payable},
             message=f"Maternity case {case.reference}: {employee.name_en}, {days} days from {fmt(start)}")
    return case


def _event(case, event, on, user, note=""):
    return MaternityEvent.objects.create(company=case.company, case=case, event=event, on=on, note=note,
                                         actor=_who(user), actor_name=actor_name(user))


def _release(case, from_day, user, why):
    """The leave ends early (a return after the ban, or a cancelled case):
    the days not yet taken go back beside the original TAKEN entry, and the
    grant for them lapses with an adjustment -- nothing is edited."""
    req = case.request
    remaining = (req.to_date - max(req.from_date, from_day)).days + 1
    if remaining <= 0:
        return 0
    effective = max(req.from_date, from_day)
    ltype, cycle = req.leave_type, req.cycle
    post(employee=case.employee, ltype=ltype, cycle=cycle, days=remaining, reason=R.CANCELLED, effective=effective,
         user=user, source_ref=req.reference,
         basis=f"{plural(remaining, 'day')} of maternity leave from {fmt(effective)} not taken: {why}")
    post(employee=case.employee, ltype=ltype, cycle=cycle, days=-remaining, reason=R.ADJUSTMENT, effective=effective,
         user=user, basis=f"The maternity grant for those {plural(remaining, 'day')} lapses with them ({why})")
    if from_day <= req.from_date:
        req.status = S.CANCELLED
    else:
        req.to_date = from_day - timedelta(days=1)
        req.days_consumed = req.days_consumed - remaining
    req.save(update_fields=["status", "to_date", "days_consumed", "updated_at"])
    return remaining


def record_event(company, reference, event, *, on=None, date_=None, note="", user=None):
    """One ordered transition function. The order is the statute's, so an
    out-of-sequence event is refused here rather than left to whichever
    button was rendered."""
    on = _date(on, "on") if on else clock.today()
    if on > clock.today():
        raise LeaveRefused({"on": ["An event is recorded once it has happened."]}, status=400)
    with transaction.atomic():
        case = (MaternityCase.objects.select_for_update().filter(company=company, reference=reference)
                .select_related("employee__company", "request__cycle", "request__leave_type", "rule_set").first())
        if case is None:
            raise LeaveRefused({"case": [f"No maternity case {reference}."]}, status=404)
        if case.status in ("COMPLETED", "CANCELLED"):
            raise LeaveRefused({"case": [f"{case.reference} is {case.get_status_display().lower()}."]}, status=409)
        rules = Book().rules(case.notice_date)
        sch = schedule(case, rules)
        e = case.employee
        refuse = lambda msg: LeaveRefused({"event": [msg]}, status=409)  # noqa: E731

        if event == M.PROOF_OF_PREGNANCY:
            if case.proof_of_pregnancy_on:
                raise refuse("Proof of pregnancy is already on the record.")
            if on < case.notice_date:
                raise refuse("Proof cannot predate the notice.")
            case.proof_of_pregnancy_on = on
            due, why = add_working_days(e, on, rules.maternity_pay_working_days)
            text = (f"First instalment due {fmt(due)}" if due else f"First instalment due in "
                    f"{rules.maternity_pay_working_days} working days — {why}") if case.benefit_payable \
                else "No benefit is payable on this case"
            _event(case, event, on, user, text)
            if case.benefit_payable:
                emit(company, E.MATERNITY_PAYMENT_DUE, employee=e, entity_ref=case.reference, actor=user,
                     payload={"instalment": 1, "due": due.isoformat() if due else None,
                              "amount": money_str(case.first_instalment_amount)},
                     message=f"{case.reference}: first maternity instalment for {e.name_en} due "
                             f"{fmt(due) if due else 'soon'}")
        elif event in (M.PAY_FIRST, M.PAY_SECOND):
            first = event == M.PAY_FIRST
            if not case.benefit_payable:
                raise refuse("No benefit is payable on this case, so no instalment is paid.")
            if first and not case.proof_of_pregnancy_on:
                raise refuse("The first instalment falls due on proof of pregnancy, which is not yet recorded.")
            if first and case.first_instalment_paid_on:
                raise refuse("The first instalment is already paid.")
            if not first and not case.first_instalment_paid_on:
                raise refuse("The first instalment is unpaid, so the second cannot be paid.")
            if not first and not case.proof_of_birth_on:
                raise refuse("The second instalment falls due on proof of birth, which is not yet recorded.")
            if not first and case.second_instalment_paid_on:
                raise refuse("The second instalment is already paid.")
            due = sch["firstInstalmentDue" if first else "secondInstalmentDue"]
            late = due is not None and on > due
            amount = case.first_instalment_amount if first else case.second_instalment_amount
            if first:
                case.first_instalment_paid_on, case.status = on, "ON_LEAVE_PRE"
            else:
                case.second_instalment_paid_on, case.status = on, "ON_LEAVE_POST"
            _event(case, event, on, user,
                   f"৳{money_str(amount)} for {rules.maternity_before if first else rules.maternity_after} days"
                   + (f" — paid {(on - due).days} days after {fmt(due)}: late payment is an offence under s.47"
                      if late else ""))
        elif event == M.DELIVERY:
            actual = _date(date_, "date") if date_ else None
            if actual is None:
                raise refuse("The date of delivery is required.")
            if case.actual_delivery:
                raise refuse("The delivery is already on the record.")
            if actual < case.notice_date:
                raise refuse("The delivery cannot predate the notice.")
            if actual > clock.today():
                raise refuse("A delivery in the future cannot be recorded as having happened.")
            _deliver(case, actual, rules, user)
            drift = (actual - case.expected_delivery).days
            _event(case, event, on, user,
                   ("On the expected date" if drift == 0 else f"{abs(drift)} days {'after' if drift > 0 else 'before'} "
                    "the expected date") + f" · post-natal leave and the {rules.maternity_ban_weeks}-week employment "
                                           "ban run from here")
        elif event == M.PROOF_OF_BIRTH:
            if not case.actual_delivery:
                raise refuse("Record the delivery before its proof.")
            if case.proof_of_birth_on:
                raise refuse("Proof of birth is already on the record.")
            if on < case.actual_delivery:
                raise refuse("Proof of birth cannot predate the delivery.")
            case.proof_of_birth_on = on
            deadline = sch["proofOfBirthDue"]
            text = (f"Filed after the {rules.maternity_proof_months}-month deadline of {fmt(deadline)}: recorded "
                    "against the case; the benefit is not forfeited") if deadline and on > deadline \
                else f"Within the {rules.maternity_proof_months}-month deadline"
            _event(case, event, on, user, text)
            if case.benefit_payable:
                due, _ = add_working_days(e, on, rules.maternity_pay_working_days)
                emit(company, E.MATERNITY_PAYMENT_DUE, employee=e, entity_ref=case.reference, actor=user,
                     payload={"instalment": 2, "due": due.isoformat() if due else None,
                              "amount": money_str(case.second_instalment_amount)},
                     message=f"{case.reference}: second maternity instalment for {e.name_en} due "
                             f"{fmt(due) if due else 'soon'}")
        elif event == M.RETURN:
            if not case.actual_delivery:
                raise refuse("A return cannot be recorded before the delivery.")
            # s.45: employing a woman within the ban is prohibited outright.
            if on < case.employment_ban_end:
                raise refuse(f"Employment within {rules.maternity_ban_weeks} weeks of the delivery is prohibited. "
                             f"The ban ends {fmt(case.employment_ban_end)}.")
            early = on <= case.post_leave_to
            released = _release(case, on, user, "returned to work early") if early else 0
            case.returned_on, case.status = on, "COMPLETED"
            _event(case, event, on, user,
                   f"Early return, after the employment ban: {plural(released, 'day')} of leave not taken"
                   if early else f"On or after the expected return of {fmt(sch['expectedReturn'])}")
        elif event == M.CANCEL:
            if case.first_instalment_paid_on:
                raise refuse("An instalment has been paid, so this case is not cancelled: record the outcome instead.")
            why = (note or "").strip()
            if len(why) < 10:
                raise LeaveRefused({"note": ["Give the reason for cancelling, at least 10 characters."]})
            released = _release(case, on, user, f"case cancelled — {why}")
            case.cancelled_on, case.cancel_reason, case.status = on, why, "CANCELLED"
            _event(case, event, on, user, f"{why} · {plural(released, 'day')} of leave released")
        else:
            raise LeaveRefused({"event": [f"Unknown maternity event {event!r}."]}, status=400)
        case.save()
        audit(company, case, A.MATERNITY_EVENT, user, on_behalf_of=e, reason=note or "",
              after={"event": event, "on": on.isoformat(), "status": case.status})
    return case


def _deliver(case, actual, rules, user):
    """The post-delivery leave is protected: a late delivery extends the
    leave so the days after it are never short, by an adjustment beside
    the original grant. The ban and the protection run from the birth."""
    req, cycle = case.request, case.request.cycle
    needed_to = actual + timedelta(days=rules.maternity_after - 1)
    extra = (needed_to - case.post_leave_to).days
    if extra > 0:
        added_from = case.post_leave_to + timedelta(days=1)
        LeaveCycle.objects.filter(pk=cycle.pk).update(ends_on=needed_to)
        cycle.refresh_from_db()
        post(employee=case.employee, ltype=req.leave_type, cycle=cycle, days=extra, reason=R.ADJUSTMENT,
             effective=added_from, user=user,
             basis=f"Delivery on {fmt(actual)}: post-delivery leave protected at {rules.maternity_after} days, so "
                   f"{plural(extra, 'day')} added to {fmt(needed_to)}")
        post(employee=case.employee, ltype=req.leave_type, cycle=cycle, days=-extra, reason=R.TAKEN,
             effective=added_from, user=user, source_ref=req.reference,
             basis=f"Maternity leave extended to {fmt(needed_to)}: {plural(extra, 'day')} ({req.reference})")
        req.to_date = needed_to
        req.days_consumed = req.days_consumed + extra
        req.save(update_fields=["to_date", "days_consumed", "updated_at"])
        case.post_leave_to = needed_to
        case.total_days_granted += extra
    case.actual_delivery = actual
    case.post_leave_from = actual
    case.pre_leave_to = actual - timedelta(days=1)
    case.status = "DELIVERED"
    protect = rules.maternity_protection
    case.protection_end = actual + timedelta(weeks=int(protect.get("afterWeeks", 8)))
    case.employment_ban_end = actual + timedelta(weeks=rules.maternity_ban_weeks)


def record_delivery(company, reference, *, actual_delivery, user=None):
    return record_event(company, reference, M.DELIVERY, date_=actual_delivery, user=user)


# ================================================================= protection


def separation_block(employee, on):
    """s.50: a woman is protected from dismissal from six months before the
    delivery to eight weeks after it. A separation in that window needs an
    authorised override with a reason. None when she is not protected."""
    case = (MaternityCase.objects.filter(employee=employee, protection_start__lte=on, protection_end__gte=on)
            .exclude(status="CANCELLED").order_by("-created_at").first())
    if case is None:
        return None
    return {"case": case.reference, "from": case.protection_start.isoformat(), "to": case.protection_end.isoformat(),
            "message": f"{employee.name_en} is protected from {fmt(case.protection_start)} to {fmt(case.protection_end)} "
                       f"by maternity case {case.reference}. A separation in that window needs an authorised "
                       "override with a reason.",
            "citation": "Bangladesh Labour Act 2006, s.50"}


def read_restricted(company, reference, *, user, allowed):
    """Every read of a restricted field is logged -- a refused read too. A
    line manager sees that the employee is on approved leave and the dates,
    and nothing more."""
    case = MaternityCase.objects.filter(company=company, reference=reference).select_related("employee").first()
    if case is None:
        raise LeaveRefused({"case": [f"No maternity case {reference}."]}, status=404)
    for f in RESTRICTED_MATERNITY_FIELDS:
        audit(company, case, A.RESTRICTED_READ if allowed else A.RESTRICTED_READ_REFUSED, user,
              on_behalf_of=case.employee, reason=f)
    if not allowed:
        raise LeaveRefused({"permission": [
            "These fields are restricted to HR. A line manager sees that the employee is on approved leave and the "
            "dates, and nothing more. This attempt has been recorded."]}, status=403)
    return {"expectedDelivery": case.expected_delivery.isoformat(),
            "actualDelivery": case.actual_delivery.isoformat() if case.actual_delivery else None,
            "survivingChildren": case.surviving_children}


# ====================================================================== reads


def case_out(case, *, figures, today=None):
    """No restricted field, ever: the expected and actual delivery dates and
    the surviving children are read one at a time, logged. The dates that
    derive from them (leave, ban, protection) are the employer's own
    obligations and are shown."""
    today = today or clock.today()
    rules = Book().rules(case.notice_date)
    sch = schedule(case, rules)
    nxt = next_action(case, sch, today)
    iso = lambda d: d.isoformat() if isinstance(d, date) else d  # noqa: E731
    alt = None
    if figures and case.reference_lines and len(rules.maternity_basis_options) > 1:
        other = next(k for k in rules.maternity_basis_options if k != case.benefit_basis)
        b = compute_benefit(case.reference_lines, other, rules.maternity_before, rules.maternity_after)
        alt = {"basis": other, "label": rules.maternity_basis_options[other].get("label"),
               "benefit": money_str(b["benefit"]), "difference": money_str(abs(b["benefit"] - case.benefit_amount))
               if case.benefit_payable else None}
    money = (lambda v: money_str(v)) if figures else (lambda v: None)  # noqa: E731
    return {
        "reference": case.reference, "employee": {"code": case.employee.code, "nameEn": case.employee.name_en,
                                                  "department": case.employee.department.title
                                                  if case.employee.department else None},
        "status": case.status, "statusLabel": case.get_status_display(),
        "noticeDate": iso(case.notice_date), "noticeMethod": case.notice_method,
        "noticeRecordedBy": case.notice_recorded_by_name or None,
        "leaveFrom": iso(case.pre_leave_from), "leaveTo": iso(case.post_leave_to),
        "totalDays": case.total_days_granted, "benefitPayable": case.benefit_payable,
        "eligibility": case.eligibility_reason, "serviceMonths": case.service_months,
        "serviceMonthsMet": case.service_months_met,
        "protectionStart": iso(case.protection_start), "protectionEnd": iso(case.protection_end),
        "employmentBanEnd": iso(case.employment_ban_end), "request": case.request.reference,
        "deliveryRecorded": case.actual_delivery is not None,
        "benefit": {
            "basis": case.benefit_basis, "basisLabel": case.get_benefit_basis_display(),
            "electedBy": case.basis_elected_by_name or None, "text": case.benefit_basis_text if figures else None,
            "lines": [{**x, "wage": x["wage"] if figures else None} for x in case.reference_lines],
            "averageDailyWage": money(case.average_daily_wage), "days": case.benefit_days,
            "amount": money(case.benefit_amount), "first": money(case.first_instalment_amount),
            "second": money(case.second_instalment_amount), "other": alt, "masked": not figures,
        },
        "dates": {
            "proofOfPregnancy": iso(case.proof_of_pregnancy_on), "firstPaid": iso(case.first_instalment_paid_on),
            "proofOfBirth": iso(case.proof_of_birth_on), "secondPaid": iso(case.second_instalment_paid_on),
            "returned": iso(case.returned_on), "cancelled": iso(case.cancelled_on),
        },
        # Before the birth, the pre-natal end is the expected delivery less a day: restricted.
        "schedule": {k: iso(v) for k, v in sch.items() if not (k == "preNatalEnd" and case.actual_delivery is None)},
        "next": {**nxt, "due": iso(nxt["due"])},
        "events": [{"event": x.event, "label": x.get_event_display(), "on": iso(x.on), "note": x.note,
                    "by": x.actor_name or None} for x in case.events.all()],
    }


def cases(company, *, figures):
    today = clock.today()
    qs = (MaternityCase.objects.filter(company=company)
          .select_related("employee__department", "request", "rule_set").prefetch_related("events"))
    rows = [case_out(c, figures=figures, today=today) for c in qs]
    open_rows = [r for r in rows if r["status"] not in ("COMPLETED", "CANCELLED")]
    committed = sum((Decimal(r["benefit"]["amount"] or 0) for r in open_rows), ZERO) if figures else None
    return {"rows": rows, "open": len(open_rows), "overdue": sum(1 for r in open_rows if r["next"]["overdue"]),
            "committed": money_str(committed) if figures else None, "masked": not figures}


__all__ = ["benefit_preview", "cases", "open_case", "read_restricted", "record_delivery", "record_event",
           "separation_block"]
