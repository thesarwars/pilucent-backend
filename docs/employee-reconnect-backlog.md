# Employee reconnect backlog

_154 references across 54 files._

Stage 1 of the BD employee module (see `docs/employee-profile.md`) removed the US `employeeio`
module outright: all ten models, twenty-five enums, the serializers, signals and helpers, every
migration, and the US employee API in `weapi`. This file is every place outside the module that
referred to any of it — the fix-up queue for the payroll phase, so breakage is found here and not
by accident.

**How to read it.** Line numbers are as of the strip commit. Only the items needed for
`manage.py check` and the test suite to pass were fixed in Phase 1; they are marked **[fixed]**
where that happened. Everything else is still broken at runtime and waits for the payroll phase.

**How it was produced.** An AST scan of imports from `employeeio`, plus a pattern scan for removed
`Employee` fields and helpers read through an employee-like receiver (`employee.`, `emp.`,
`self.employee.`, `employee__` lookups, serializer `source=`), reverse accessors to the removed
child models, and `ssn`. A receiver the scan did not recognise will not be listed — treat the list
as the floor, not the ceiling.

## Phase 1 reconnect log

What was reconnected to get `manage.py check` and the test suite green, and how.
"Fixed" means the project imports and boots -- not that the US behaviour
behind it works on BD employees.

- **datamigrationio** — the three employee-import services imported
  `EmployeeKindChoices` at app-ready time, so nothing booted. The spreadsheet's
  employment-type column maps onto BD `EmploymentTypeChoices`
  (FULL_TIME / PART_TIME / CONTRACT), so the import was renamed. The importer's
  `create()` and the validator still speak US columns (first/last name, kind);
  a BD employee import is its own piece of work.
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

## What the BD `Employee` still answers to

`uid`, `code`, `status` (`EmployeeStatusChoices`: DRAFT / ACTIVE / IN_ACTIVE / REMOVED), `user`,
`company` (related name `employees`), `department`, `designation`, `shift`, `father_name`.
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

