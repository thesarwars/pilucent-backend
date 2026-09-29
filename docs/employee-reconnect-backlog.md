# Employee reconnect backlog

_154 references across 54 files._

Stage 1 of the BD employee module (see `docs/employee-profile.md`) removed the US `employeeio`
module outright: all ten models, twenty-five enums, the serializers, signals and helpers, every
migration, and the US employee API in `weapi`. This file is every place outside the module that
referred to any of it — the fix-up queue for the payroll phase, so breakage is found here and not
by accident.

**How to read it.** Line numbers are as of the strip commit. Phase 1 fixed what `manage.py
check` and the test suite needed, plus every break found on a non-payroll path (login, company,
accounting, dashboards, notifications); those are marked **[fixed]** below and described in the
reconnect log. Everything else is still broken at runtime and waits for the payroll phase — the
confirmed list is under "Still broken".

**How it was produced.** An AST scan of imports from `employeeio`, plus a pattern scan for removed
`Employee` fields and helpers read through an employee-like receiver (`employee.`, `emp.`,
`self.employee.`, `employee__` lookups, serializer `source=`), reverse accessors to the removed
child models, and `ssn`. A receiver the scan did not recognise will not be listed — treat the list
as the floor, not the ceiling.

## Phase 1 reconnect log

What was reconnected to get `manage.py check` and the test suite green, and how.
"Fixed" means the project imports and boots -- not that the US behaviour
behind it works on BD employees.

- **Login access (every login was broken)** — `has_login_access` queries
  `Employee.is_access_enabled`, and the strip removed that column with the US
  model, so password, TOTP and Google sign-in and onboarding raised
  `FieldError` for *every* user, employee-linked or not. `is_access_enabled` and
  `is_joined` are account behaviour, not HR, and are restored on the BD
  `Employee` with their old defaults (migration `0002_employee_login_access`).
  The only way to grant access lived in the removed US employee API; it is now
  `PATCH /we/employees/{code}/access {isAccessEnabled}`, open only to an admin
  *of the active company* (its system admin role — not the global `is_admin`
  flag that every self-signup carries into companies it was merely invited to;
  `IsCompanyAdmin` has that gap and still guards the role endpoints). Granting
  and the invitation email are one locked, atomic step, so a failed send leaves
  access off and a retry sends again. The lock is `FOR UPDATE OF` the employee
  row only: `user` is a nullable FK, and PostgreSQL refuses a bare FOR UPDATE on
  the nullable side of the outer join — which SQLite, and so the test suite,
  cannot show. The email uses a BD template without the
  US "Password: <email>" line. Revoking is silent and works without a linked
  login; deleting a login clears its employees' access flags, so a grant cannot
  pass to whoever is linked next. Granting with no linked login is a 409.
  Linking a login to a BD employee (the US create-with-user flow) is not rebuilt:
  that is the self-service onboarding phase.
- **Superuser and developer registration** — `create_superuser` and
  `custom_user_register` created an employee with no company (`company_email=`).
  They now create the company first, then a BD employee in it (next `EMP-` code,
  `name_en` from the user). Access keeps its default (off), as before.
- **User onboarding admin** — responses no longer carry the US HR
  `employee_id` (the BD business key is `code`, already present); setting a
  different `employee_code` is refused ("never reassigned") during validation,
  before the user or an uploaded image is saved; the same code is accepted. The
  employee shown and checked is the one in the editor's active company. Before,
  a user employed by two companies could show the other company's code,
  designation and department, and whether a user was listed at all ("joined",
  "is_employee") was decided by their employee record in *any* company; every
  employee predicate in the list is now scoped to the active company, and the
  detail view is a 404 when there is no active company (an unscoped lookup
  matched any user with no membership).
- **Chart-of-account register** — search matched `employee__first_name` /
  `last_name` (every search raised `FieldError`); it now matches `name_en` /
  `name_bn`. The payee column resolved names through US fields and would have
  rendered every payroll leg's payee **blank**; it now reads `name_en`.
- **Chat expense-report test** — `chatio/tests_expense_report_sides.py` guarded
  the journal sides of the removed expense-report posting (literal
  "addition"/"substraction" inverted on a credit-card payment account). Deleted
  with the feature; **re-add that guard when expense reports are rebuilt.**
- **Purging users** — `purge_users` promises to take a purged user's employee
  records with it. The US `Employee.user` cascaded; the BD one is `SET_NULL`,
  because an employee is the company's statutory record and outlives a deleted
  login in ordinary use. The command now collects the users' employees
  explicitly, inside the same guarded collector run, and its plan no longer
  lists them a second time as "nulled". `EmployeeSalaryStructure.superseded_by`
  is `RESTRICT` rather than `PROTECT` (migration 0003): a superseding structure
  still cannot be deleted on its own, but PROTECT refused any purge — and any
  company delete — of an employee whose salary had been revised.
- **Model `__str__` on a login-less employee** — two payroll models (one is
  `PayrollSalaryProcess`) printed `employee.user.name`, and two attendance
  models `employee.user`. The audit log calls `str()` on every save and delete it
  records, so any such row for a BD employee without a login crashed auditing.
  They print `employee.name_en`.
- **Names through `created_by` / `actor`** — `created_by` on sales, purchases,
  bills and many settings models, and `actor` on subscription events, are
  foreign keys to `Employee`. Names read through them fell back to "someone" or
  blank. Sale and purchase notifications and the subscription audit log read
  `name_en` now.
- **HR dashboard cards** — employee overview and upcoming events queried
  `confirmation_date`, `date_of_birth`, `contract_end_date` (every call raised);
  the pending-leave card showed "Unknown" for every name. The US model used the
  confirmation date as a stand-in for joining; the BD one has `doj`, so joiners
  and work anniversaries (after a full year) count from `doj`, birthdays from
  `dob`, contract ends from `contract_end`. "Upcoming confirmations" counts
  unconfirmed, unseparated probationers whose `probation_end` falls in the
  window — a future `confirmation` date is a data error the BD contract blocks
  payroll on. Still open: `status` is the record lifecycle, not employment, so
  a separated employee stays ACTIVE and remains in headcount, birthdays and
  anniversaries until "currently employed" is defined with the separation flow
  (doc §6.3).
- **Admin search** — `leaveio` (three admins) searched `employee__name` and
  `payrollio`'s accounting-preferences admin `created_by__name`; any search term
  raised. They search `name_en`.
- **datamigrationio** — the three employee-import services imported
  `EmployeeKindChoices` at app-ready time, so nothing booted. The spreadsheet's
  employment-type column maps onto BD `EmploymentTypeChoices`
  (FULL_TIME / PART_TIME / CONTRACT), so the import was renamed. The importer's
  `create()` still writes US columns and failed on every row inside the Celery
  task, so the "employees" migration type is switched off: `import_available`
  and `template_available` are False, confirm / dry run / rollback are refused
  by the views, validate and review-impact answer "not implemented" instead of
  running the US validator, and the US template (SSN, US country) is no longer
  served. A BD employee import is its own piece of work.
- **Pay schedules** — `GET /we/payroll/pay-schedule/employees/<uid>/` (employees
  on a pay schedule) was built on the removed employee serializers, and a BD
  employee has no pay schedule. Its view, serializer and route are removed.
  Still mounted and **broken at request time**: `PayScheduleWithEmployeeCountView`
  annotates `Count("employee")`, a reverse relation that no longer exists.
- **Payroll accounting preferences** — the expense-account component no longer
  carries `employee_garnishment`; a client sending it has the key ignored.
  Its nested `employee` is now the BD slim shape (`uid, code, name_en, name_bn,
  photo`), not the US user shape (`email, first_name, ...`).
- **Payroll report "employee details"** — `/we/payroll/reports/employee-details/`
  read the removed banking, deduction and tax satellites. View deleted, route
  unmounted. Its builder (`payrollio/django_rest/helpers/employee_details.py`)
  and tests are kept for the payroll phase.
- **Chat expense reports** — `EmployeeExpenseReport` went with the module. The
  websocket actions `save_expense_report` and `change_expense_report_status`
  now answer through their existing error path ("Expense reports are not
  available yet."); stored expense messages still render from their payload.
- **Slim serializers** — `PrivateCompanyEmployeeSlimSerializer` and
  `PublicCompanyEmployeeSlimSerializer` are rebuilt on BD fields, so the 27
  places nesting them import cleanly. Their payload shape changed: consumers
  reading `full_name`, `employee_id` or `image` get `name_en`, `code`, `photo`.
- **Roles** — `/we/employees/<uuid>/roles` and `/extra-permissions` are kept
  (see above) and resolve BD employees by uid.

## Still broken — confirmed by the reconnect sweep, deferred

After the first pass, four independent finders swept production code for
runtime breakage (ORM lookups, attribute and template reads, writes, removed
relations), and every finding had to be reproduced by two skeptics before it
counted. A second, mechanical check resolved every string `<fk>__<field>`
lookup through each of the 9 foreign keys that point at `Employee`
(`employee`, `created_by`, `manager`, `assigned_to`, `approved_by`, `actor`,
`redeemed_by`, `closed_by`, `undone_by`) against the BD model: every lookup
that still fails is in the list below. These are the plan's deferred areas
(payroll, leave, attendance); none is on a login, company, accounting or
dashboard path.

**Attendance** (every endpoint below errors today)

- `weapi/django_rest/serializers/attendances.py:80-81` —
  `PrivateAttendanceEmployeeSerializer` lists `employee_id` and
  `source="get_image"`; DRF raises `ImproperlyConfigured`, and it is nested in
  the attendance list and detail serializers, so `GET/POST /we/attendances`,
  the detail route and the `?is_pdf=true` export all fail. BD: `code`, `photo`.
- `attendances.py:468` — `employee.holiday` (`POST /we/attendances/processes`,
  for any day without a punch record — the normal case).
- `attendances.py:525` — `Employee.objects.get(employee_id=…)`; the
  `FieldError` escapes the `except (DoesNotExist, ValueError)`
  (`POST /we/attendances/punch-data`). `:537` builds its error message from
  `employee.employee_id` and `employee.user.name` (None without a login).
- `attendanceio/django_rest/helpers/context.py:27` — `emp.holiday_id`, and
  `weapi/django_rest/serializers/attendance_bulk.py:105` — `employee.employee_id`
  (`POST /we/attendances/bulk/preview` and `/bulk/commit`).
- `templates/reports/payrolls/daily_attendances.html:100` reads `employee_id`
  and `first_name` (unreachable until the serializer above is fixed).

**Leave**

- Search raises `FieldError`: `weapi/django_rest/views/leaves/leave_balance.py:60`
  (`employee__first_name/last_name`), `leave_encashment.py:52` and
  `leave_request.py:102` (`employee__name`).
- `weapi/django_rest/serializers/leaves/leave_balance.py:180` —
  `getattr(emp, "full_name", "")` falls back to the login's name, so a BD
  employee without a login shows a blank name.

**Payroll**

- *Payroll posting* — `weapi/django_rest/helpers/salary_process_journal_entry.py:381`
  `_resolve_employee_state` reads `employee.work_locations`, so it always
  returns None and the whole state-tax credit block is skipped for every
  employee: every state tax lands on the residual `Payroll Liabilities` leg.
  The log text at `:589` still tells operators to check the work location.
  The six tests in `payrollio/tests_salary_process_entry_balance.py` that are
  about state routing are skipped with that reason (`NO_STATE_ROUTING`): they
  would otherwise pass on the no-state path without exercising what they are
  named for.
- *Reports* — `work_locations`, `first_name`/`last_name` and
  `employeebankinginformation_set` lookups raise in
  `weapi/django_rest/views/payroll/reports/paycheck.py` (40, 46, 84, 85),
  `payroll_details.py` (58, 70), `payroll_summary_by_employee.py` (64, 78) and
  its serializer (24), and `payroll/tax_center.py:59`.
- *Tenant scoping by login* — payroll reports, `payroll/salary_process.py` and
  `salary_adjustment.py:38,76` scope with `employee__user__companyuser__company`
  or `employee__user__id__in=<company users>`. Valid lookups, but a BD employee
  need not have a login, so these silently drop every employee without one.
  BD scope is `employee__company`.
- `weapi/django_rest/views/moov_money/transfer_money.py:814-815` — search on
  `employee__first_name/last_name`.

## Found alongside — pre-existing, not caused by the strip

User onboarding (`accounts/.../user_onboards.py`) reached across companies for a
user who belongs to two. Fixed in its own commit: role and permission edits
now write only the membership in the editor's company, and the list and detail
show that membership. Still open, both decisions for the owner:

- **DELETE soft-deletes the user and their employee records in every
  company.** An admin of one company can deactivate a shared user's account in
  another. Removing only this company's membership is *not* a safe fix today:
  US payroll and tax queries reach a company's runs through the membership row
  (`employee__user__companyuser__company`), so a deleted row drops that
  company's payroll history and its 940/941 figures. Either give `CompanyUser`
  a status that login, workspace selection and the onboarding list honour, or
  first scope those payroll queries by `employee__company`.
- **The edit/delete view has no admin permission** (`permission_classes` is
  commented out), so any member of a company can edit or remove other members.

## What the BD `Employee` still answers to

`uid`, `code`, `status` (`EmployeeStatusChoices`: DRAFT / ACTIVE / IN_ACTIVE / REMOVED), `user`,
`company` (related name `employees`), `department`, `designation`, `shift`, `father_name`,
`is_access_enabled`, `is_joined`.
`gender` survives as a name but its values are now `MALE / FEMALE / THIRD_GENDER`. A slim nested
serializer is still exported as `PrivateCompanyEmployeeSlimSerializer`, rebuilt on BD fields.

Renamed rather than removed — the BD field to reach for:

| US field | BD field |
|---|---|
| `first_name / middle_name / last_name / name` | `name_en (and name_bn)` |
| `date_of_birth` | `dob` |
| `nid_card_no` | `nid` |
| `phone_number` | `mobile` |
| `personal_email / company_email / preferred_email` | `email` |
| `blood_group` | `blood` |
| `confirmation_date` | `confirmation` |
| `contract_end_date` | `contract_end` |
| `report_to` | `manager` |
| `image` | `photo` |
| `emergency_contact_name / _relationship / emergency_phone_number` | `emergency_name / emergency_relation / emergency_phone` |
| `terminate_date / terminate_kind` | `separated_on / separation_type` |
| `kind (employment kind)` | `employment_type; worker_category; classification` |
| `EmployeeBankingInformation` | `EmployeePaymentProfile (1:1: bank / MFS / cash)` |
| `EmployeeTax` | `EmployeeTaxProfile (1:1)` |
| `EmployeeSalary` | `EmployeeSalaryStructure + components (effective-dated)` |

No BD equivalent, by design: `ssn`, `citizenship_kind`, `uscis_or_alien_registration_number`, `pay_schedule`,
`work_locations`, `holiday`, `salary_frequency`, `pay_kind`, `total_salary`, `total_rate_per_hour`, the
overtime flags, `EmployeeEducation`, `EmployeeWorkExperience`, `EmployeeEarning`,
`EmployeeDeductionContribution`, `EmployeeGarnishment`, `EmployeeExpenseReport`.

## Removed API routes

Callers of these get a 404 until the BD API replaces what they need. The role and permission
routes under `/employees/<uuid>/roles` and `/extra-permissions` were **kept** — they are access
control, not US payroll, and they only use `Employee.uid` and `Employee.user`, which survive.

| Route | View |
|---|---|
| `/api/v1/we/employees/<uuid:uid>/job-card-overview` | `PrivateWeEmployeeJobCardOverView` |
| `/api/v1/we/employees/<uuid:uid>/documents/<uuid:document_uid>` | `PrivateWeEmployeeDocumentDetails` |
| `/api/v1/we/employees/<uuid:uid>/documents` | `PrivateWeEmployeeDocumentList` |
| `/api/v1/we/employees/<uuid:uid>/work-experiences/<uuid:work_experience_uid>` | `PrivateWeEmployeeWorkExperienceDetails` |
| `/api/v1/we/employees/<uuid:uid>/work-experiences` | `PrivateWeEmployeeWorkExperienceList` |
| `/api/v1/we/employees/<uuid:uid>/garnishments/<uuid:garnishment_uid>` | `PrivateWeEmployeeGarnishmentDetails` |
| `/api/v1/we/employees/<uuid:uid>/garnishments` | `PrivateWeEmployeeGarnishmentList` |
| `/api/v1/we/employees/garnishments-list` | `PrivateWeCompanyGarnishmentList` |
| `/api/v1/we/employees/<uuid:uid>/deduction-contributions/<uuid:deduction_and_contribution_uid>` | `PrivateWeEmployeeDeductionContributionDetails` |
| `/api/v1/we/employees/<uuid:uid>/deduction-contributions` | `PrivateWeEmployeeDeductionContributionList` |
| `/api/v1/we/employees/<uuid:uid>/earnings/<uuid:earning_uid>` | `PrivateWeEmployeeEarningDetails` |
| `/api/v1/we/employees/<uuid:uid>/earnings` | `PrivateWeEmployeeEarningList` |
| `/api/v1/we/employees/<uuid:uid>/educations/<uuid:education_uid>` | `PrivateWeEmployeeEducationDetails` |
| `/api/v1/we/employees/<uuid:uid>/educations` | `PrivateWeEmployeeEducationList` |
| `/api/v1/we/employees/<uuid:uid>/taxes/<uuid:tax_uid_uid>` | `PrivateWeEmployeeTaxDetails` |
| `/api/v1/we/employees/<uuid:uid>/taxes` | `PrivateWeEmployeeTaxList` |
| `/api/v1/we/employees/<uuid:uid>/banking-informations/<uuid:banking_information_uid>` | `PrivateWeEmployeeBankingInformationDetails` |
| `/api/v1/we/employees/<uuid:uid>/banking-informations` | `PrivateWeEmployeeBankingInformationList` |
| `/api/v1/we/employees/<uuid:uid>` | `PrivateWeEmployeeDetails` |
| `/api/v1/we/employees` | `PrivateWeEmployeeList` |
| `/api/v1/we/employees/list` | `PrivateWeEmployeeListAll` |
| `/api/v1/we/salaries` | `PrivateWeCompanyEmployeeSalaryList` |
| `/api/v1/we/salary/<uuid:uid>` | `PrivateWeSalaryDetails` |

## Found by hand

- `accounts/django_rest/helpers/group_seeds.py:44-47` — seeds `view`/`change` permissions on
  `employeesalary`, `employeetax`, `employeebankinginformation`. Those content types no longer exist.
- `common/django_rest/helpers/account_references.py:77` — lists `employeeio.EmployeeExpenseReport` as
  a chart-of-account referrer.
- `payrollio/models.py` — `PayrollAccountExpenseAccountComponent.employee_garnishment` removed; its
  `AddField` was taken out of `payrollio/migrations/0028_…` instead of reversed by a new migration,
  because a later `RemoveField` cannot run once the target model is gone from the graph. **[fixed]**
- `staticfiles/` is not versioned in pilucent. The US W-4, I-9, 941 and 944 PDF templates the
  `weapi/django_rest/views/pdf/` views open from it are therefore absent; those views are US-only.
- `Employee.completed_payroll_runs` returns 0 until the BD payroll phase records runs. It drives the
  retroactive-change warning on classification changes (doc §6.1).
- `location` (doc §2.2) has no BD home yet: the US `work_locations` FK pointed at payrollio.

## By app

### weapi — 99

**`weapi/django_rest/helpers/dashboard/hr.py`**

- L441 — `emp.date_of_birth` — reads a US `Employee` field the BD model does not have
- L447 — `emp.date_of_birth` — reads a US `Employee` field the BD model does not have
- L451 — `emp.confirmation_date` — reads a US `Employee` field the BD model does not have
- L452 — `emp.confirmation_date` — reads a US `Employee` field the BD model does not have
- L459 — `emp.confirmation_date` — reads a US `Employee` field the BD model does not have
- L463 — `emp.contract_end_date` — reads a US `Employee` field the BD model does not have
- L469 — `emp.contract_end_date` — reads a US `Employee` field the BD model does not have

**`weapi/django_rest/helpers/payroll/paycheck_report.py`**

- L126 — `.get_addresses(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L209 — `.get_bank_information(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L218 — `employee.full_name` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L346 — `.get_bank_information(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L352 — `employee.full_name` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L464 — `employee.full_name` — calls a US `Employee` helper (payroll/attendance/leave-coupled)

**`weapi/django_rest/serializers/attendance_bulk.py`**

- L105 — `employee.employee_id` — reads a US `Employee` field the BD model does not have

**`weapi/django_rest/serializers/attendances.py`**

- L67 — `source="get_image"` — serializer `source=` points at a removed field or helper
- L101 — `source="get_ot_hour_count"` — serializer `source=` points at a removed field or helper
- L468 — `employee.holiday` — reads a US `Employee` field the BD model does not have
- L537 — `employee.employee_id` — reads a US `Employee` field the BD model does not have

**`weapi/django_rest/serializers/employee_salaries.py`**

- L4 — `PrivateEmployeeSalarySlimSerializer` from `employeeio.django_rest.serializers.common` — imports a model, enum or serializer that no longer exists
- L7 — `EmployeeBankingInformation` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L7 — `EmployeeSalary` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L23 — `EmployeeSalaryKind` from `employeeio.choices` — imports a model, enum or serializer that no longer exists

**`weapi/django_rest/serializers/employees.py`**

- L62 — `EmployeeBankingInformationStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L62 — `EmployeeDeductionContributionStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L62 — `EmployeeEarningStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L62 — `EmployeeEducationStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L62 — `EmployeeGarnishmentStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L62 — `EmployeeOnboardingKindChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L62 — `EmployeeWorkExperienceStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L72 — `PrivateEmployeeBankingInformationSlimSerializer` from `employeeio.django_rest.serializers.common` — imports a model, enum or serializer that no longer exists
- L76 — `EmployeeBankingInformation` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L76 — `EmployeeDeductionContribution` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L76 — `EmployeeEarning` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L76 — `EmployeeEducation` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L76 — `EmployeeGarnishment` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L76 — `EmployeeTax` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L76 — `EmployeeWorkExperience` from `employeeio.models` — imports a model, enum or serializer that no longer exists

**`weapi/django_rest/serializers/payroll/accounting_preferences.py`** — **[fixed]** garnishment handling removed; the key is popped and ignored

- L21 — `EmployeeGarnishment` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L164 — `employee_garnishment` — uses `PayrollAccountExpenseAccountComponent.employee_garnishment`
- L210 — `employee_garnishment` — uses `PayrollAccountExpenseAccountComponent.employee_garnishment`
- L219 — `employee_garnishment` — uses `PayrollAccountExpenseAccountComponent.employee_garnishment`

**`weapi/django_rest/serializers/payroll/pay_schedule.py`** — **[fixed]** assigned-employee serializer removed with its view

- L17 — `weapi.django_rest.serializers.employees` — imports from the removed US employee API module
- L32 — `PrivateEmployeeBankingInformationSlimSerializer` from `employeeio.django_rest.serializers.common` — imports a model, enum or serializer that no longer exists
- L123 — `source="get_company_role"` — serializer `source=` points at a removed field or helper
- L128 — `source="get_addresses"` — serializer `source=` points at a removed field or helper
- L132 — `source="get_banking_informations"` — serializer `source=` points at a removed field or helper
- L136 — `source="get_first_tax"` — serializer `source=` points at a removed field or helper
- L147 — `employeegarnishment_set` — walks a reverse relation to a removed child model
- L150 — `employeeearning_set` — walks a reverse relation to a removed child model
- L156 — `employeedeductioncontribution_set` — walks a reverse relation to a removed child model
- L271 — `.get_worked_hours(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L273 — `.get_worked_hours(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L282 — `.get_paid_leave_hour_count(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L285 — `.get_un_paid_leave_hour_count(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L288 — `.get_ot_hour_count(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L291 — `.get_partial_paid_leave_hour_count(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)
- L295 — `.get_leave_requests(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)

**`weapi/django_rest/serializers/payroll/salary_process.py`**

- L28 — `source="work_locations.` — serializer `source=` points at a removed field or helper
- L219 — `obj.employee.get_company` — calls a US `Employee` helper (payroll/attendance/leave-coupled)

**`weapi/django_rest/serializers/payroll/work_location.py`**

- L6 — `PublicCompanyEmployeeSlimSerializer` from `employeeio.django_rest.serializers.common` — imports a model, enum or serializer that no longer exists

**`weapi/django_rest/urls/__init__.py`**

- L26 — `weapi.django_rest.urls.employees` — imports from the removed US employee API module

**`weapi/django_rest/urls/we.py`**

- L21 — `from ..views.employee_salaries import` — imports from the removed US employee API module
- L22 — `from ..views.employee_salaries import` — imports from the removed US employee API module

**`weapi/django_rest/views/attendances.py`**

- L69 — `.get_ot_hour_count(` — calls a US `Employee` helper (payroll/attendance/leave-coupled)

**`weapi/django_rest/views/chart_of_accounts.py`**

- L460 — `employee__first_name` — queries through a US `Employee` field
- L461 — `employee__last_name` — queries through a US `Employee` field

**`weapi/django_rest/views/employee_salaries.py`**

- L9 — `EmployeeSalary` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L11 — `EmployeeSalaryStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists

**`weapi/django_rest/views/employees.py`**

- L26 — `EmployeeBankingInformation` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L26 — `EmployeeDeductionContribution` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L26 — `EmployeeEarning` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L26 — `EmployeeEducation` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L26 — `EmployeeGarnishment` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L26 — `EmployeeTax` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L26 — `EmployeeWorkExperience` from `employeeio.models` — imports a model, enum or serializer that no longer exists

**`weapi/django_rest/views/leaves/leave_balance.py`**

- L60 — `employee__first_name` — queries through a US `Employee` field
- L60 — `employee__last_name` — queries through a US `Employee` field

**`weapi/django_rest/views/leaves/leave_encashment.py`**

- L52 — `employee__name` — queries through a US `Employee` field

**`weapi/django_rest/views/leaves/leave_request.py`**

- L102 — `employee__name` — queries through a US `Employee` field

**`weapi/django_rest/views/moov_money/bank_account_settings.py`**

- L338 — `employee.is_banking_info_verified` — reads a US `Employee` field the BD model does not have
- L492 — `employee.is_banking_info_verified` — reads a US `Employee` field the BD model does not have

**`weapi/django_rest/views/moov_money/transfer_money.py`**

- L814 — `employee__first_name` — queries through a US `Employee` field
- L815 — `employee__last_name` — queries through a US `Employee` field

**`weapi/django_rest/views/payroll/pay_schedule.py`** — **[fixed]** assigned-employee view and route removed

- L6 — `from ..employees import` — imports from the removed US employee API module

**`weapi/django_rest/views/payroll/reports/employee_details.py`** — **[fixed]** deleted and unmounted

- L21 — `EmployeeBankingInformation` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L21 — `EmployeeDeductionContribution` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L21 — `EmployeeTax` from `employeeio.models` — imports a model, enum or serializer that no longer exists

**`weapi/django_rest/views/payroll/reports/multiple_worksite.py`**

- L241 — `employee.work_locations` — reads a US `Employee` field the BD model does not have

**`weapi/django_rest/views/payroll/reports/paycheck.py`**

- L40 — `employee__work_locations` — queries through a US `Employee` field
- L84 — `employee__first_name` — queries through a US `Employee` field
- L85 — `employee__last_name` — queries through a US `Employee` field

**`weapi/django_rest/views/payroll/reports/payroll_details.py`**

- L58 — `employee__work_locations` — queries through a US `Employee` field
- L70 — `employee__first_name` — queries through a US `Employee` field
- L70 — `employee__last_name` — queries through a US `Employee` field

**`weapi/django_rest/views/payroll/reports/payroll_summary_by_employee.py`**

- L64 — `employee__work_locations` — queries through a US `Employee` field
- L78 — `employee__first_name` — queries through a US `Employee` field
- L78 — `employee__last_name` — queries through a US `Employee` field

**`weapi/django_rest/views/payroll/tax_center.py`**

- L59 — `employee__work_locations` — queries through a US `Employee` field

**`weapi/django_rest/views/pdf/i9.py`**

- L100 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)

### payrollio — 22

**`payrollio/django_rest/helpers/employee_details.py`**

- L162 — `employee.salary_frequency` — reads a US `Employee` field the BD model does not have
- L276 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L276 — `employee.ssn` — reads a US `Employee` field the BD model does not have
- L335 — `employee.date_of_birth` — reads a US `Employee` field the BD model does not have
- L336 — `employee.gender` — reads a US `Employee` field the BD model does not have
- L339 — `employee.work_locations` — reads a US `Employee` field the BD model does not have
- L348 — `employee.description` — reads a US `Employee` field the BD model does not have

**`payrollio/django_rest/helpers/payroll_report_common.py`**

- L54 — `employee.last_name` — reads a US `Employee` field the BD model does not have
- L58 — `employee.first_name` — reads a US `Employee` field the BD model does not have
- L59 — `employee.middle_name` — reads a US `Employee` field the BD model does not have

**`payrollio/django_rest/helpers/tax_center_rollup.py`**

- L403 — `employee.work_locations` — reads a US `Employee` field the BD model does not have

**`payrollio/django_rest/serializer/common.py`** — **[fixed]** expense-account component nests the BD slim employee; garnishment field dropped

- L21 — `PrivateEmployeeUserSerializer` from `employeeio.django_rest.serializers.common` — imports a model, enum or serializer that no longer exists
- L21 — `PrivateWeEmployeeGarnishmentSlimSerializer` from `employeeio.django_rest.serializers.common` — imports a model, enum or serializer that no longer exists
- L180 — `employee_garnishment` — uses `PayrollAccountExpenseAccountComponent.employee_garnishment`
- L191 — `employee_garnishment` — uses `PayrollAccountExpenseAccountComponent.employee_garnishment`

**`payrollio/models.py`**

- L571 — `employee_garnishment` — uses `PayrollAccountExpenseAccountComponent.employee_garnishment`

**`payrollio/tests/test_employee_details.py`**

- L25 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L43 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L139 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L380 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)

**`payrollio/tests/test_tax_center_rollup.py`**

- L51 — `employee.work_locations` — reads a US `Employee` field the BD model does not have

**`payrollio/tests_salary_process_entry_balance.py`**

- L309 — `employee.work_locations` — reads a US `Employee` field the BD model does not have

### datamigrationio — 11

**`datamigrationio/django_rest/handlers/employees.py`**

- L71 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L72 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L73 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)

**`datamigrationio/django_rest/services/employee_importer.py`** — **[fixed]** enum import renamed to `EmploymentTypeChoices`; `create()` still writes US fields

- L16 — `EmployeeKindChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L91 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L104 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L171 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)

**`datamigrationio/django_rest/services/employee_validator.py`** — **[fixed]** enum import renamed to `EmploymentTypeChoices`; still validates US columns (first/last name)

- L8 — `EmployeeKindChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists
- L132 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)
- L392 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)

**`datamigrationio/django_rest/services/row_fix.py`** — **[fixed]** enum import renamed to `EmploymentTypeChoices`

- L55 — `EmployeeKindChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists

### accounts — 10

**`accounts/django_rest/serializers/onboards.py`**

- L36 — `employee.is_joined` — reads a US `Employee` field the BD model does not have

**`accounts/django_rest/serializers/user_onboards.py`**

- L224 — `emp.employee_id` — reads a US `Employee` field the BD model does not have
- L227 — `emp.is_joined` — reads a US `Employee` field the BD model does not have
- L228 — `emp.is_access_enabled` — reads a US `Employee` field the BD model does not have
- L293 — `emp.employee_id` — reads a US `Employee` field the BD model does not have
- L296 — `emp.is_joined` — reads a US `Employee` field the BD model does not have
- L297 — `emp.is_access_enabled` — reads a US `Employee` field the BD model does not have

**`accounts/django_rest/serializers/workspace.py`**

- L57 — `employee.is_access_enabled` — reads a US `Employee` field the BD model does not have

**`accounts/django_rest/views/user_onboards.py`**

- L73 — `employee__is_joined` — queries through a US `Employee` field

**`accounts/models.py`**

- L59 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)

### chatio — 4

**`chatio/django_rest/helpers/expense_report.py`** — **[fixed]** deleted with the model

- L13 — `EmployeeExpenseReport` from `employeeio.models` — imports a model, enum or serializer that no longer exists
- L14 — `EmployeeExpenseReportStatusChoices` from `employeeio.choices` — imports a model, enum or serializer that no longer exists

**`chatio/django_rest/serializers/chat_rooms.py`** — **[fixed]** expense-report serializer removed

- L7 — `EmployeeExpenseReport` from `employeeio.models` — imports a model, enum or serializer that no longer exists

**`chatio/django_rest/views/chat_rooms.py`** — **[fixed]** expense messages render from the stored event payload

- L27 — `EmployeeExpenseReport` from `employeeio.models` — imports a model, enum or serializer that no longer exists

### leaveio — 3

**`leaveio/admin.py`**

- L34 — `employee__name` — queries through a US `Employee` field
- L42 — `employee__name` — queries through a US `Employee` field
- L57 — `employee__name` — queries through a US `Employee` field

### meapi — 2

**`meapi/django_rest/serializer/profiles.py`**

- L97 — `employee.is_joined` — reads a US `Employee` field the BD model does not have
- L102 — `employee.is_access_enabled` — reads a US `Employee` field the BD model does not have

### adminio — 1

**`adminio/django_rest/serializers/admin_permissions.py`**

- L24 — `source="name"` — serializer `source=` points at a removed field or helper

### attachmentio — 1

**`attachmentio/django_rest/serializers/common.py`**

- L7 — `source='image.` — serializer `source=` points at a removed field or helper

### moovmoneyio — 1

**`moovmoneyio/django_rest/helpers/moov_connection.py`**

- L36 — `ssn` — US Social Security Number — no BD equivalent (BD identity is `nid`)

