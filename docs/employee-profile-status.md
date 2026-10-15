# Employee profile — implementation status

Against the contract in `docs/employee-profile.md`. Everything in §2–§11 is
built; this file records where the backend departs from the letter of the
contract or the front end, and what is still somebody's decision.

## Where things live

| Contract | Code |
|---|---|
| §3 compliance, incl. both wage floors | `employeeio/services/compliance.py` |
| §5 templates, assignment, revision, arrears | `employeeio/services/salary.py`, `services/periods.py` |
| §6 classification, separation | `employeeio/services/gated.py` |
| §7.1–7.4 gratuity, overtime, bonus, leave, proration | `employeeio/services/statutory.py` |
| §7.5 tax projection | `employeeio/services/tax.py` |
| §7.6 withholding deadlines | `employeeio/services/withholding.py` (in the tax-projection response) |
| §9 documents | `employeeio/services/documents.py` |
| §10 words, numerals, grouping | `common/words.py` |
| §9 API | `weapi/django_rest/views/bd_employees.py` |

Acceptance tests: 1, 11, 14 `tests_api`; 2 `tests_compliance` + `tests_salary`; 3
`tests_tax_projection`; 4–6, 10 `tests_compliance`; 7 `tests_salary`; 8
`tests_gated`; 9, 13 `tests_statutory`; 12 `rulebookio/tests_rule_book`.

## Processed periods

Reopened periods and arrears (§5.2) need to know which payroll periods are
processed. `ProcessedPayrollPeriod` (company, month) is that ledger. The BD
payroll run is meant to write a row when it completes a period; until it
exists nothing writes it, so every revision reopens nothing and the next
unprocessed period is the current month. `Employee.completed_payroll_runs`
counts the same rows (periods within service, with a structure in force).

"Backdated" means before the next unprocessed period — not before today — so
the default effective date never needs a reason.

## Deviations, each deliberate

- **`FOOD` salary component.** The contract lists BASIC, HRA, MED, CONV, DA.
  The RMG gazette has a food allowance, without which an RMG structure cannot
  reach its own total-wage floor.
- **RMG transport is 450, not the screen's 350.** 350 is the 2018 gazette;
  the 2023 gazette's 6,700 + 3,350 + 750 + 450 + 1,250 = 12,500.
  `rmgAllowances` is DRAFTED in the rule book.
- **Gratuity monthly provision is one year's gratuity ÷ 12** (the screen's
  `salDerive`), not the accrued total ÷ 12 that §7.1 literally reads.
- **Graduated resignation bands** are compared with gratuity only where the
  band says so (10+ years), as §6.3 states. `calc.js` compared every band.
- **Separation eligibility is on completed years.** The band, a minimum
  service and the death-compensation year use completed service; only the
  days × years multiplication counts a part-year over six months. `calc.js`
  used the rounded count for both, so seven months qualified as a year.
- **"Gratuity, if any"** (s.20, s.26): with `gratuityEligible` off the
  higher-of test compares with nil.
- **RMG default basic** is the grade's basic floor, raised where needed to the
  lowest basic that also clears the grade's total floor — the drafted G1/G2
  totals do not reconcile with their basics.
- **WORKING_26 proration** no longer counts weekly holidays as days lost;
  `payroll-calc.js` did, which docked a full month by 4/26. Backdated arrears
  for a part period use calendar actual when the election is WORKING_26 or
  HOURS_208, because the weekly holidays and hours are not on file.
- **A classification change cannot be dated in the future.** Classification
  is one column, not an effective-dated record; applied early it would drop
  the year's projected festival bonuses. Record it on or after its date.
- **A separation blocks payroll from its date**, not from when it is
  recorded, so notice periods are still paid.
- **Rule-book keys added** beyond `rules.js`, so nothing is inlined:
  `withholding.*` (tax sets from 2026-27 only — 2025-26 has none, and the
  projection says so), `dayWageDivisor` (30), `rmgAllowances`, and the
  service-book / appointment-letter / ID-card citations.
- **Standard template is 7% medical / 3% conveyance** per the contract. The
  test fixture `give_structure` keeps `fixtures.js`'s 6% / 4% split and is
  not a template-built structure.

## Open decisions

- **Who may make gated changes.** Salary assignment and revision,
  classification and separation are open only to an admin of the active
  company (`IsActiveCompanyAdmin`). The front end's `salary.edit` /
  `salary.approve` role model is not wired to the backend yet; nothing yet
  enforces `salary.view` on reads.
- **Floors are checked for everyone.** With no grade recorded, the default
  (lowest-grade) floor applies. The floor values are DRAFTED and still block
  a save; the response carries their confidence.
- **Late deposit counts a started month as a month** (§7.6). Confirm
  against s.143.
- **Documents are data, not PDFs.** Issuing freezes the filled template;
  rendering is the client's. Preconditions: the service book needs both
  parents' names, a valid NID, the permanent address and the joining date;
  the appointment letter a joining date, designation and salary structure;
  the ID card a photograph and designation.
- **The Bangla 1–99 table** (ported from `words.js`) has not been reviewed
  by a native speaker.
