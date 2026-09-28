**BALANZIFY**  
**Accounting Platform  ·  Product & Engineering**

**Recurring Transactions**

**Bill Module**

End-to-End Product Requirements & Technical Specification

*Feature goals · User stories · Functional spec · User flows · Data model · APIs · Business rules · Integrations*

| Field | Detail |
| :---- | :---- |
| Document title | Recurring Transactions (Bill) — Product & Technical Requirements Document |
| Product area | Expenses domain · Accounts Payable · Recurring Transactions |
| Prepared for | Balanzify Product, Engineering & QA teams |
| Document type | Feature specification / build reference (developer-facing) |
| Version | 1.0 (Initial release for build) |
| Status | **Ready for development** |
| Prerequisite modules | Sales module, Expense module, Vendor master, Chart of Accounts, Products & Services, Tax engine |
| Related future work | Recurring Invoice, Recurring Expense, Recurring Journal Entry (same engine) |

# **Table of Contents**

[**Table of Contents	2**](#heading=)

[**1\. Introduction & Purpose	3**](#heading=)

[1.1 Who this document is for	3](#heading=)

[1.2 How to read it	3](#heading=)

[**2\. Glossary & Terminology	3**](#heading=)

[**3\. Feature Goals & Objectives	5**](#heading=)

[3.1 Business goals	5](#heading=)

[3.2 User goals	5](#heading=)

[3.3 Non-goals (explicitly out of scope for v1)	5](#heading=)

[3.4 Success metrics	6](#heading=)

[**4\. Competitive Research & Market Analysis (R\&D)	7**](#heading=)

[4.1 Research method	7](#heading=)

[4.2 What the market has in common	7](#heading=)

[4.3 Where platforms differ	8](#heading=)

[4.4 Feature parity matrix	8](#heading=)

[**5\. Scope, Assumptions & Dependencies	10**](#heading=)

[5.1 In scope (v1)	10](#heading=)

[5.2 Out of scope (v1)	10](#heading=)

[5.3 Assumptions	10](#heading=)

[5.4 Dependencies	10](#heading=)

[**6\. User Personas	12**](#heading=)

[6.1 Priya — Small Business Owner	12](#heading=)

[6.2 Marcus — Bookkeeper / Finance Ops	12](#heading=)

[6.3 Dana — Operations Manager	12](#heading=)

[**7\. Concept Model & Feature Overview	13**](#heading=)

[7.1 Template vs. generated bill (the parent–child model)	13](#heading=)

[7.2 The three template types	13](#heading=)

[7.3 Where the feature lives in Balanzify	14](#heading=)

[7.4 Template lifecycle	14](#heading=)

[7.5 End-to-end example	14](#heading=)

[**8\. User Stories & Acceptance Criteria	16**](#heading=)

[Epic A — Viewing recurring transactions	16](#heading=)

[RB-01  See all recurring templates	16](#heading=)

[RB-02  Filter and find quickly	16](#heading=)

[Epic B — Creating a recurring bill template	16](#heading=)

[RB-03  Start a new template and choose the type	16](#heading=)

[RB-04  Configure a Scheduled bill	16](#heading=)

[RB-05  Configure a Reminder bill	17](#heading=)

[RB-06  Configure an Unscheduled bill	17](#heading=)

[RB-07  Build the bill body (lines, memo, attachment)	17](#heading=)

[Epic C — Acting on templates	17](#heading=)

[RB-08  Edit a template safely	17](#heading=)

[RB-09  Use a template on demand	18](#heading=)

[RB-10  Duplicate a template	18](#heading=)

[RB-11  Delete a template	18](#heading=)

[Epic D — Reminders & automation	18](#heading=)

[RB-12  Work the reminders queue	18](#heading=)

[RB-13  Automatic generation on time	19](#heading=)

[**9\. Detailed Functional Specification	20**](#heading=)

[9.1 Recurring Transactions list	20](#heading=)

[9.1.1 Columns	20](#heading=)

[9.1.2 Toolbar & controls	20](#heading=)

[9.1.3 States	21](#heading=)

[9.2 New → Select Transaction Type	21](#heading=)

[9.3 Recurring Bill template form	21](#heading=)

[9.3.1 Header — template name & type	21](#heading=)

[9.3.2 Behavior — Type \= Scheduled	22](#heading=)

[9.3.3 Behavior — Type \= Reminder	22](#heading=)

[9.3.4 Behavior — Type \= Unscheduled	22](#heading=)

[9.3.5 Vendor, mailing address & terms	22](#heading=)

[9.3.6 Interval configuration (the frequency engine)	22](#heading=)

[9.3.7 Start date, End condition & Autopay	23](#heading=)

[9.3.8 Category details (account-based lines)	23](#heading=)

[9.3.9 Item details (product/service lines)	24](#heading=)

[9.3.10 Totals, memo & attachments	24](#heading=)

[9.3.11 Save / Cancel	24](#heading=)

[9.4 Row actions (Edit / Use / Duplicate / Delete)	25](#heading=)

[9.5 Reminders List	25](#heading=)

[9.5.1 Columns & controls	25](#heading=)

[9.5.2 Behavior	25](#heading=)

[9.6 “Make recurring” from an existing bill	26](#heading=)

[**10\. User Flows	27**](#heading=)

[10.1 Flow — Create a Scheduled recurring bill	27](#heading=)

[10.2 Flow — Automatic generation (background)	27](#heading=)

[10.3 Flow — Reminder template, then process the reminder	28](#heading=)

[10.4 Flow — Use an Unscheduled template on demand	28](#heading=)

[10.5 Flow — Edit a template (safely)	28](#heading=)

[10.6 Flow — Delete a template	28](#heading=)

[**11\. Business Rules & Scheduling Engine	30**](#heading=)

[11.1 Computing the Next Date	30](#heading=)

[11.2 Month-end clamping	30](#heading=)

[11.3 Days-in-advance creation (Scheduled)	31](#heading=)

[11.4 Reminder timing (Reminder)	31](#heading=)

[11.5 End conditions	31](#heading=)

[11.6 The Generation Job	31](#heading=)

[11.6.1 Cadence & timezone	31](#heading=)

[11.6.2 Selection query	32](#heading=)

[11.6.3 Idempotency (no duplicates)	32](#heading=)

[11.6.4 Catch-up after downtime	32](#heading=)

[11.6.5 Failure handling	32](#heading=)

[11.7 What a generated bill inherits from the template	32](#heading=)

[11.8 Concurrency & ordering	32](#heading=)

[**12\. Data Model	34**](#heading=)

[12.1 Entities & relationships	34](#heading=)

[12.2 recurring\_template	34](#heading=)

[12.3 recurring\_schedule (fields / value object)	35](#heading=)

[12.4 recurring\_template\_line	36](#heading=)

[12.5 recurring\_occurrence (run log & reminders)	36](#heading=)

[12.6 New columns on the Bill entity	37](#heading=)

[12.7 Sample template (JSON)	37](#heading=)

[**13\. API Specification	38**](#heading=)

[13.1 Endpoint summary	38](#heading=)

[13.2 List templates	38](#heading=)

[13.3 Create template	39](#heading=)

[13.4 Use a template now	39](#heading=)

[13.5 List & resolve reminders	39](#heading=)

[13.6 Standard error model	40](#heading=)

[**14\. Integration with Other Modules	41**](#heading=)

[**15\. Edge Cases, Validation & Error Handling	42**](#heading=)

[15.1 Field validation rules	42](#heading=)

[15.2 Behavioral edge cases	42](#heading=)

[15.3 Error-handling principles	43](#heading=)

[**16\. Permissions & Roles	44**](#heading=)

[**17\. Non-Functional Requirements	45**](#heading=)

[17.1 Performance	45](#heading=)

[17.2 Scalability & multi-tenancy	45](#heading=)

[17.3 Reliability & correctness	45](#heading=)

[17.4 Security & privacy	46](#heading=)

[17.5 Time zones, dates & internationalization	46](#heading=)

[17.6 Availability & observability	46](#heading=)

[**18\. Notifications	47**](#heading=)

[18.1 Reminder notifications (Reminder-type templates)	47](#heading=)

[18.2 Generation summaries (optional, Scheduled templates)	47](#heading=)

[18.3 Failure & exception alerts	47](#heading=)

[18.4 Channels & preferences	47](#heading=)

[**19\. Analytics & Reporting	49**](#heading=)

[19.1 User-facing report — Recurring Templates	49](#heading=)

[19.2 Product instrumentation & success metrics	49](#heading=)

[19.3 Operational dashboards	50](#heading=)

[**20\. QA & Acceptance Checklist	51**](#heading=)

[20.1 List & navigation	51](#heading=)

[20.2 Creating templates (all three types)	51](#heading=)

[20.3 Scheduling engine & generation	51](#heading=)

[20.4 Row actions, reminders & integrity	52](#heading=)

[**21\. Future Enhancements	54**](#heading=)

[21.1 More recurring transaction types	54](#heading=)

[21.2 Lifecycle controls	54](#heading=)

[21.3 Payments & autopay	54](#heading=)

[21.4 Power-user & scale features	54](#heading=)

[**22\. Appendix	55**](#heading=)

[22.1 Field quick-reference	55](#heading=)

[22.2 Type-behavior summary	55](#heading=)

[22.3 Change log	55](#heading=)

*Tip: right-click the table above in Word and choose “Update Field” to refresh page numbers.*

# **1\. Introduction & Purpose**

This document is the single source of truth for the Recurring Transactions – Bill feature in Balanzify. It is written so that a product manager, a backend engineer, a frontend engineer, a QA engineer, or a new team member can each read it end-to-end and understand not just what to build, but why it exists, how it behaves in every state, and how it connects to the rest of the accounting platform.

Balanzify already ships a complete Sales module and a complete Expense module. Bills (money the business owes its vendors) already exist inside the Expense domain today: a user can create a one-off bill, attach line items, assign a vendor, and record it against accounts payable. What is missing is the ability to make a bill repeat. Businesses pay the same suppliers on a predictable rhythm — office rent, internet, software subscriptions, cleaning services, equipment leases — and re-typing those bills every month is slow and error-prone.

The Recurring Transactions feature solves this by letting a user save a bill once as a reusable template, attach a schedule to it, and then have Balanzify either create the bill automatically, remind the user to create it, or keep it on a shelf to be used on demand. This first release targets the Bill transaction type only, but the engine is intentionally designed so the same template, list, and scheduler can later power recurring invoices, expenses, and journal entries with minimal additional work.

## **1.1 Who this document is for**

* **Product / Project managers** — to confirm scope, goals, and acceptance criteria.

* **Backend engineers** — for the data model, scheduling engine, generation job, and API contracts.

* **Frontend engineers** — for screen-by-screen behavior, field rules, states, and user flows.

* **QA engineers** — for edge cases, validation rules, and the acceptance checklist.

* **Designers** — for the intended structure of every screen and the interaction model.

## **1.2 How to read it**

Sections 1–6 give the big picture: goals, competitive research, scope, and users. Section 7 explains the core concept model — the three template types and the parent–child relationship — that everything else depends on; read it first. Section 8 turns the concept into user stories with acceptance criteria. Sections 9–10 are the detailed, screen-by-screen functional spec and the concrete user flows. Sections 11–15 are the engineering core: business rules and the scheduling engine, the data model, API contracts, integrations, and edge cases. Sections 16 onward cover permissions, non-functional requirements, notifications, analytics, QA, and future work.

# **2\. Glossary & Terminology**

To avoid ambiguity, the whole team should use these terms consistently. They are used exactly this way throughout the document, the codebase, and the UI copy.

| Term | Definition |
| :---- | :---- |
| **Recurring Template** | The saved, reusable definition of a repeating transaction. It stores the vendor, line items, amounts, schedule, and behavior type. A template does not itself appear in the ledger — it is a blueprint. Also called simply “template”. |
| **Generated Bill** | An actual bill created from a template. This is a real, posted (or draft) transaction that lives in the Expense/AP ledger. Also called a “child transaction”. One template produces many generated bills over time. |
| **Template Type** | One of three behaviors a template can have: Scheduled, Reminder, or Unscheduled. The type decides whether Balanzify acts automatically, nudges the user, or waits to be told. |
| **Scheduled** | A template type where Balanzify creates the bill automatically on each scheduled date, with no user action required. |
| **Reminder** | A template type where Balanzify does not create the bill, but places a reminder in the Reminders List (and notifies the user) a set number of days before each date, so the user can review, edit, and create it. |
| **Unscheduled** | A template type with no timetable at all. It simply sits in the list until the user chooses “Use” to create a bill from it on demand. |
| **Interval** | The frequency rule that describes how often a Scheduled or Reminder template repeats (for example, monthly on the 1st of every 1 month). |
| **Next Date** | The next date on which the template is due to produce a bill (Scheduled) or a reminder (Reminder). Calculated by the scheduling engine. |
| **Previous Date** | The most recent date on which the template already produced a bill or reminder. Empty until the first run. |
| **Create days in advance** | For Scheduled templates: how many days before the Next Date the generated bill should actually be created and posted, so it appears early in the payables list. |
| **Remind days before** | For Reminder templates: how many days before the transaction date the reminder should appear and notify the user. |
| **End condition** | When the schedule stops: never, after a fixed number of occurrences, or on a specific end date. |
| **Generation Job** | The scheduled background process (cron/worker) that runs on a fixed cadence, finds templates that are due, and creates their bills or reminders. |
| **Autopay** | An optional setting to automatically pay a generated bill through a connected payment method. Surfaced in the UI but gated by payment availability. |

# **3\. Feature Goals & Objectives**

The feature exists to remove repetitive manual work from accounts payable while keeping the user fully in control of what gets posted to their books. Automation must never surprise the user or create records they did not expect.

## **3.1 Business goals**

* **Save time on repeat data entry.** A user should set up a repeating bill once and never re-type it.

* **Reduce errors.** Consistent templates prevent typos in amounts, accounts, and tax codes across periods.

* **Improve cash-flow visibility.** Because upcoming bills are known in advance, the payables list and reports reflect obligations before they are due.

* **Increase retention & stickiness.** Recurring templates encode a customer's operational routine into Balanzify, raising switching cost and daily engagement.

* **Reach feature parity.** Recurring transactions are table-stakes in cloud accounting. Their absence is a common reason prospects reject a product during evaluation.

## **3.2 User goals**

* Automate fixed, unchanging bills (e.g., rent) so they post without any effort.

* Get a timely nudge for bills that recur but whose amount changes (e.g., a utility bill), then adjust before posting.

* Keep a library of complex bills that are re-used irregularly, so they never have to be rebuilt from scratch.

* See, at a glance, everything that repeats, what is coming next, and how much it will cost.

* Edit, duplicate, or stop a repeating bill safely, without corrupting bills already posted.

## **3.3 Non-goals (explicitly out of scope for v1)**

Stating what we are not building is as important as stating what we are. These are deliberately excluded from the first release to keep it focused and shippable; several appear again in Section 21 as future work.

* Recurring invoices, expenses, sales receipts, or journal entries (the engine will support them later, but only Bill ships now).

* Recurring bill payments. A payment is a second-stage transaction applied against a bill; automating it separately would create ambiguity about which bill it settles. Only the bill itself recurs.

* Advanced dunning, retries, or subscription-style metered billing.

* Bulk import/export of templates via CSV (planned as a fast-follow).

* Pause / Resume / Skip-next controls (planned as a fast-follow; the data model reserves room for them).

## **3.4 Success metrics**

| Metric | Definition | Target (first 90 days) |
| :---- | :---- | :---- |
| Adoption | % of active companies with ≥1 recurring bill template | ≥ 25% |
| Template volume | Median templates per adopting company | ≥ 3 |
| Automation rate | % of recurring bills created by the job vs. manually | ≥ 60% |
| Time saved | Est. minutes saved \= generated bills × avg. manual entry time | Reported monthly |
| Generation reliability | % of due templates processed on time by the job | ≥ 99.9% |
| Error rate | % of generated bills reversed/deleted within 48h | \< 2% |

# **4\. Competitive Research & Market Analysis (R\&D)**

Before designing the feature, we studied how recurring transactions work across the leading cloud accounting platforms used by small and mid-sized businesses. The goal was to identify the mental model users already expect, the fields that are genuinely necessary, and the edge cases that mature products have learned to handle. The findings below are distilled into concrete decisions for Balanzify. To keep this document vendor-neutral, competitors are referenced as Platform A, Platform B, and Platform C rather than by brand name.

## **4.1 Research method**

* Reviewed public help documentation and setup guides for three leading platforms covering recurring bills, invoices, and expenses.

* Mapped every user-facing field, the available frequency options, and the actions offered on a saved template.

* Catalogued behavioral edge cases (month-end dates, editing a live template, deleting a template, timezone of generation).

* Synthesized a common conceptual model that users already understand, then chose the subset that best fits Balanzify's existing Bill screen.

## **4.2 What the market has in common**

Despite different naming, the three platforms converge on the same core ideas. This convergence is the strongest possible signal for what Balanzify should adopt:

* **Template-driven.** Every platform stores a reusable template that is separate from the transactions it generates.

* **Parent–child relationship.** One template (parent) produces many dated transactions (children). Editing the template affects future children only; already-generated children are never retroactively rewritten.

* **A behavior spectrum.** From fully automatic, to a reminder that requires review, to a purely manual on-demand template — the exact three types Balanzify will adopt.

* **A frequency engine.** Daily / weekly / monthly / yearly plus an “every N periods” multiplier and a day-of-week or day-of-month selector.

* **Start date \+ end condition.** A first-run date and a choice of never-ending, ending after N occurrences, or ending on a date.

* **Month-end clamping.** A monthly rule set to the 31st automatically falls back to the last valid day in shorter months (e.g., Feb 28/29).

* **Deleting stops the future only.** Removing a template halts future generation but leaves previously created bills untouched in the ledger.

## **4.3 Where platforms differ**

| Dimension | Observed variation across platforms |
| :---- | :---- |
| Behavior model | Platform A offers three explicit types (auto / reminder / on-demand). Platforms B and C lean on “auto-create as draft vs. auto-approve” toggles instead of a named reminder type. Balanzify adopts the clearer three-type model. |
| Terminology | “Recurring”, “Repeating”, and “Profile” are all used. Balanzify standardizes on “Recurring Transaction / Template”. |
| Generation timing | Some platforms create children early via a “days in advance” field; others generate exactly on the date at a fixed hour in the org's timezone. Balanzify supports both: a days-in-advance offset and a fixed daily run time. |
| Payment terms | Platform C ties a bill's due date to vendor payment terms (e.g., Net 15). Balanzify reuses its existing Terms field so due dates are derived automatically. |
| Attachments | Most platforms let you attach a file to the template but do NOT copy it onto each child. Balanzify follows this convention and documents it explicitly to avoid confusion. |
| Editing safeguards | Mature platforms warn when an item/vendor used by a template changes, offering “update all” vs. “one time only”. Balanzify adopts a lighter version of this safeguard. |
| Stop vs. pause | Platform C supports pause/resume; others only delete. Balanzify ships delete now, and reserves pause/resume for a fast-follow. |

## **4.4 Feature parity matrix**

This matrix maps notable capabilities to each researched platform and states Balanzify's decision for v1. It doubles as a scope checklist.

| Capability | Platform A | Platform B | Platform C | Balanzify v1 |
| :---- | :---- | :---- | :---- | :---- |
| Reusable templates | **✔** | **✔** | **✔** | **✔ Yes** |
| Scheduled (auto-create) | ✔ | ✔ | ✔ | **✔ Yes** |
| Reminder type | ✔ | partial | partial | **✔ Yes** |
| Unscheduled type | ✔ | ✔ | ✔ | **✔ Yes** |
| Interval multiplier (every N) | ✔ | ✔ | ✔ | **✔ Yes** |
| Day-of-week / day-of-month | ✔ | ✔ | ✔ | **✔ Yes** |
| End after N / on date / never | ✔ | ✔ | ✔ | **✔ Yes** |
| Days-in-advance creation | ✔ | — | — | **✔ Yes** |
| Month-end clamping | ✔ | ✔ | ✔ | **✔ Yes** |
| Autopay on generated bill | ✔ | ✔ | ✔ | **◐ UI \+ gate** |
| Use / Duplicate / Delete | ✔ | ✔ | ✔ | **✔ Yes** |
| Pause / Resume / Skip | — | — | ✔ | Fast-follow |
| CSV import of templates | — | — | ✔ | Fast-follow |

| R\&D takeaway Balanzify will adopt the three-type behavior model (Scheduled / Reminder / Unscheduled) because it is the clearest mental model and maps directly to the three real user needs: fixed bills, variable bills, and irregular bills. Everything else in this document follows from that decision. |
| :---- |

# **5\. Scope, Assumptions & Dependencies**

## **5.1 In scope (v1)**

* A central Recurring Transactions list page that displays all recurring bill templates.

* A “New” flow that asks which transaction type to create (Bill only in v1) and opens the recurring bill template form.

* A recurring bill template form supporting all three types, full interval configuration, start/end conditions, category lines, item lines, memo, attachment, and terms.

* A background Generation Job that creates Scheduled bills and raises Reminder items on time.

* A Reminders List page showing reminder-type items that are due for the user to act on.

* Row actions: Edit, Use, Duplicate, Delete.

* Full integration with the existing Vendor, Chart of Accounts, Products & Services, Tax, and Bill/AP ledger modules.

* Audit logging of template create/edit/delete and every generated bill.

## **5.2 Out of scope (v1)**

* All non-Bill transaction types (invoice, expense, etc.).

* Recurring bill payments and autopay execution (autopay is surfaced but gated — see Section 9.3.7).

* Pause/Resume/Skip, CSV import/export, and multi-currency-specific handling beyond what the base Bill screen already supports.

## **5.3 Assumptions**

* The one-off Bill screen, Vendor master, Chart of Accounts, Products & Services, and Tax engine already exist and are stable — recurring bills reuse them rather than reimplement them.

* Each company (tenant) has a configured time zone; all schedule calculations use it.

* A reliable background job runner (cron/queue/worker) is available in the platform infrastructure.

* Users are already authenticated and scoped to a company; standard role-based permissions apply.

## **5.4 Dependencies**

| Depends on | Why |
| :---- | :---- |
| Vendor master | Each template must reference a vendor; mailing address and default terms are pulled from it. |
| Chart of Accounts | Category lines post to expense/asset accounts; the AP account is used when the bill is created. |
| Products & Services | Item lines reference catalog items with their rate, description, and income/expense account. |
| Tax engine | Line-level tax codes and totals are computed by the existing tax service. |
| Bill / AP ledger | Generated bills are real bills; they must be created through the same service and validations as manual bills. |
| Terms / payment terms | Due date on a generated bill is derived from the vendor/template terms. |
| Background job runner | The Generation Job needs a scheduler that runs at least daily at the org's chosen time. |
| Notifications service | Reminders and (optionally) generation summaries are delivered here. |
| Attachments / file store | Templates can hold an attachment reference. |
| Audit log | Template and generated-bill events are recorded for traceability. |

# **6\. User Personas**

Three primary personas drive the requirements. Each maps to one of the three template types, which is a useful way to sanity-check that the design serves real needs.

### **6.1 Priya — Small Business Owner**

**Context:** Runs a 6-person design studio. Handles her own books between client work. Not an accountant.

**Pain:** Pays the same rent and software bills every month and keeps forgetting to enter them until they are overdue.

**Needs:** Fixed bills posted automatically with zero effort → Scheduled templates.

**Success looks like:** She sets up rent once and never thinks about entering it again; it just appears in payables.

### **6.2 Marcus — Bookkeeper / Finance Ops**

**Context:** Manages books for several client companies. Detail-oriented, cares about accuracy over speed.

**Pain:** Utility and usage-based bills recur but the amount changes each month; he does not want them posted blindly.

**Needs:** A reliable nudge a few days before each bill is due, so he can key the real amount and post it → Reminder templates.

**Success looks like:** He opens the Reminders List, sees what is due, updates the figure, and creates each bill in seconds.

### **6.3 Dana — Operations Manager**

**Context:** Handles procurement for a mid-sized firm. Deals with complex, multi-line vendor bills that recur irregularly.

**Pain:** Rebuilding a 15-line equipment bill from scratch each time it is needed is tedious and mistake-prone.

**Needs:** A saved library of complex bills to pull from on demand, no schedule → Unscheduled templates.

**Success looks like:** When the order comes in, she clicks “Use”, tweaks a couple of lines, and the bill is done.

| Design principle across all three Automation is opt-in and reversible. Priya's bills post automatically because she chose Scheduled; Marcus stays in control because he chose Reminder; Dana keeps everything manual because she chose Unscheduled. The user always picks how much control to give up. |
| :---- |

# **7\. Concept Model & Feature Overview**

This section defines the ideas the entire feature is built on. If a reader understands only one section of this document, it should be this one — the detailed spec, data model, and APIs are all direct expressions of the model described here.

## **7.1 Template vs. generated bill (the parent–child model)**

A recurring bill has two distinct kinds of records, and keeping them separate is the most important architectural decision in the feature:

* **The template (parent).** A reusable blueprint. It holds the vendor, line items, amounts, tax codes, schedule, and behavior type. It is not a financial transaction and never appears in the general ledger, reports, or the aged-payables total.

* **The generated bill (child).** A real bill, identical in every way to a bill the user could have typed by hand. It has its own bill number, bill date, due date, and status; it posts to accounts payable and shows up everywhere a normal bill would.

One template produces many generated bills over its lifetime. The link between them is preserved so the user (and support) can always trace which template created which bill, but the two records live independently afterwards.

| The golden rule of editing Editing a template changes future generated bills only. Bills that were already created are never rewritten when the template changes. This protects the integrity of posted books — a bill that has been paid or reconciled must not silently change because someone updated the template months later. |
| :---- |

## **7.2 The three template types**

Every template has exactly one type. The type is the single most important choice the user makes, because it decides how much the system does automatically. The three types form a spectrum from fully automated to fully manual.

| Type | What the system does | Best for | User's job |
| :---- | :---- | :---- | :---- |
| **Scheduled** | Creates the bill automatically on each scheduled date (optionally a set number of days early). | Fixed bills that never change — rent, lease payments, flat-rate subscriptions. | Set it up once, then nothing. Review occasionally. |
| **Reminder** | Does NOT create the bill. Places a reminder in the Reminders List and notifies the user a set number of days before the date. | Bills that recur on a rhythm but whose amount changes — utilities, usage-based services. | Respond to the reminder: review, adjust the amount, and create the bill. |
| **Unscheduled** | Nothing on a timetable. Keeps the template on the shelf until asked. | Complex bills reused irregularly — occasional equipment or supply orders. | Click “Use” whenever the bill is actually needed. |

A user can change a template's type at any time. Switching to Scheduled or Reminder reveals the interval and start/end fields; switching to Unscheduled hides them because an unscheduled template has no timetable.

## **7.3 Where the feature lives in Balanzify**

Recurring Transactions is a shared list that can host multiple transaction types, but in v1 it hosts bills only. Conceptually it sits in the Expenses domain alongside the existing Bill and Expense screens, because a bill is an accounts-payable transaction. The entry points are:

* **Recurring Transactions list** — reached from the Expenses/Lists area; the home base for every template.

* **“Make recurring” on an existing bill** — a shortcut that turns a bill the user is already editing into a template (see Section 9.6).

* **Reminders List** — a focused view of reminder-type items that are due for action.

## **7.4 Template lifecycle**

A template moves through a simple, predictable lifecycle. Understanding it makes the scheduling engine (Section 11\) and the states in the UI easy to follow.

| Stage | What happens |
| :---- | :---- |
| **Created** | The user saves a template. If it is Scheduled or Reminder, the engine computes its first Next Date from the start date and interval. |
| **Active** | The template is live. On each due date the Generation Job either creates a bill (Scheduled) or raises a reminder (Reminder). Previous Date and Next Date advance after each run. Unscheduled templates are “active” only in the sense that they can be Used at any time. |
| **Ended** | The schedule reaches its end condition (last occurrence reached, or end date passed). No further bills or reminders are produced. The template remains visible for reference and can be reactivated by editing its end condition. |
| **Deleted** | The user deletes the template. Future generation stops immediately. All bills already generated remain untouched in the ledger. The template is soft-deleted so history and audit links survive. |

## **7.5 End-to-end example**

To make the model concrete, here is a Scheduled rent bill from setup to steady state:

1. On 1 June, Priya opens New → Bill, names the template “Monthly Building Lease”, chooses Scheduled, picks vendor “Hall Properties”, adds one category line for $900 to Rent Expense, sets Monthly on the 1st of every 1 month, start date 1 July, end None, and Create 0 days in advance.

2. Balanzify saves the template and calculates Next Date \= 1 July. Nothing is posted yet.

3. On 1 July the Generation Job finds the template due, creates a real $900 bill dated 1 July for Hall Properties, links it to the template, then advances Previous Date \= 1 July and Next Date \= 1 August.

4. The bill appears in payables like any other. Priya pays it when ready.

5. This repeats every month with zero effort until Priya edits or deletes the template.

# **8\. User Stories & Acceptance Criteria**

The requirements are expressed as user stories grouped into epics. Each story uses the standard “As a … I want … so that …” form and is followed by testable acceptance criteria (AC). QA should be able to write test cases directly from the AC. Story IDs (RB-xx) are stable references used elsewhere in the document.

## **Epic A — Viewing recurring transactions**

### **RB-01  See all recurring templates**

As a *user managing my books*, I want a single list of every recurring bill template so that I can see everything that repeats in one place.

#### **Acceptance criteria**

* The list shows columns: Template Name, Type, Txn Type, Interval, Previous Date, Next Date, Vendor, Amount, and an Action menu.

* Templates are sortable by Template Name, Next Date, Vendor, and Amount.

* A “Filter by name” box narrows the list as the user types.

* When there are no templates, an empty state explains what recurring transactions are and offers a “New” action.

* Amounts display in the company's base currency with correct formatting.

### **RB-02  Filter and find quickly**

As a *bookkeeper with many templates*, I want to filter the list so that I can find a specific template fast.

#### **Acceptance criteria**

* Name filter matches on partial, case-insensitive text.

* A type/txn filter lets the user narrow to a transaction type (Bill) or template type.

* Pagination appears when the list exceeds one page; the current range (e.g., “1–2”) is shown.

## **Epic B — Creating a recurring bill template**

### **RB-03  Start a new template and choose the type**

As a *user*, I want to create a new recurring transaction and pick which type of transaction it is, so that I can build the right kind of template.

#### **Acceptance criteria**

* Selecting “New” opens a “Select Transaction Type” dialog with a dropdown.

* In v1 the dropdown contains Bill (the architecture allows more types later).

* Confirming opens the recurring bill template form; cancelling returns to the list with no changes.

### **RB-04  Configure a Scheduled bill**

As *Priya (owner)*, I want to set a bill to post automatically so that fixed bills like rent are entered without me.

#### **Acceptance criteria**

* Choosing Type \= Scheduled reveals a “Create \_\_ days in advance” field.

* Interval, Start date, and End condition fields are shown and required.

* On save, the engine computes the first Next Date and the template becomes active.

* On each due date the bill is created automatically and linked to the template.

### **RB-05  Configure a Reminder bill**

As *Marcus (bookkeeper)*, I want to be reminded before a variable bill is due so that I can enter the correct amount and post it myself.

#### **Acceptance criteria**

* Choosing Type \= Reminder reveals a “Remind \_\_ days before the transaction date” field.

* No bill is ever created automatically for a Reminder template.

* On the reminder date, an item appears in the Reminders List and a notification is sent.

* From the reminder, the user can open, edit, and create the bill in one flow.

### **RB-06  Configure an Unscheduled bill**

As *Dana (ops manager)*, I want to save a complex bill without a schedule so that I can reuse it whenever it is actually needed.

#### **Acceptance criteria**

* Choosing Type \= Unscheduled hides the interval and start/end fields and shows an explanatory note.

* The template saves with no Next Date and never generates a bill on its own.

* The template can be turned into a bill anytime via the Use action.

### **RB-07  Build the bill body (lines, memo, attachment)**

As a *user*, I want the template to capture the same detail as a normal bill so that generated bills are complete and correct.

#### **Acceptance criteria**

* Category details lines support Category (account), Description, Amount, Billable, Tax, and Customer.

* Item details lines support Product/Service, Description, Qty, Rate, Amount, Billable, Tax, and Customer.

* Add/remove line rows; a running Total is displayed and matches the sum of all lines and tax.

* Memo and a single Attachment (≤ 20 MB) can be added to the template.

* Vendor selection auto-fills the mailing address and default Terms.

## **Epic C — Acting on templates**

### **RB-08  Edit a template safely**

As a *user*, I want to edit a template so that future bills reflect new amounts, accounts, or schedules — without disturbing bills already posted.

#### **Acceptance criteria**

* Edit opens the template pre-filled with its current values.

* Saving recalculates Next Date if the interval or start date changed.

* Changes never alter bills already generated.

* If a referenced item or vendor was changed elsewhere, the user is informed how it affects the template.

### **RB-09  Use a template on demand**

As a *user*, I want to create a bill from a template immediately so that I can post an occurrence whenever I choose.

#### **Acceptance criteria**

* Use opens a pre-filled bill (editable) or creates it directly, depending on template type.

* For Unscheduled and Reminder templates, Use is the primary way to produce a bill.

* The created bill is linked to the template and appears in payables.

### **RB-10  Duplicate a template**

As a *user*, I want to duplicate an existing template so that I can create a similar one without rebuilding it.

#### **Acceptance criteria**

* Duplicate creates a copy pre-filled with all fields, named “Copy of …”.

* The copy is independent; editing it does not affect the original.

* The copy starts with no run history (empty Previous Date).

### **RB-11  Delete a template**

As a *user*, I want to delete a template so that it stops generating bills — while keeping the bills it already created.

#### **Acceptance criteria**

* Delete asks for confirmation and warns that future generation will stop.

* After delete, no further bills/reminders are produced.

* Bills already generated remain in the ledger, unchanged.

* The action is recorded in the audit log.

## **Epic D — Reminders & automation**

### **RB-12  Work the reminders queue**

As *Marcus*, I want a dedicated list of reminder items that are due so that I can process variable bills efficiently.

#### **Acceptance criteria**

* The Reminders List shows reminder items due now, with Template Name, Txn Type, Interval, Txn Date, Amount, and Vendor.

* The list supports find-by-name and a transaction-type filter.

* Each item offers an action to create the bill; batch actions allow processing several at once.

* When nothing is due, the list shows a clear empty state.

### **RB-13  Automatic generation on time**

As *Priya*, I want scheduled bills to be created reliably on their date so that I can trust the automation.

#### **Acceptance criteria**

* The Generation Job runs at least daily at the company's configured time.

* Every template due (accounting for days-in-advance) is processed exactly once per occurrence.

* Month-end rules are honored (e.g., the 31st becomes the last day of a shorter month).

* If the job is delayed, missed occurrences are caught up without creating duplicates.

# **9\. Detailed Functional Specification**

This section specifies every screen in the feature: its layout, each field, the rules that govern it, and the states it can be in. Field tables use a consistent shape — Field, Control, Required, and Behavior/Rules — so engineers and QA can work directly from them. Screens are described in the order a user encounters them.

## **9.1 Recurring Transactions list**

The list is the home of the feature. It shows all recurring templates for the company and is where users go to review, create, and act on templates. The screen has a header (title, feedback link, a view switcher, and a New button), a toolbar (name filter, a Filter control, and a “Manage recurring payments” link), and the templates table.

### **9.1.1 Columns**

| Column | Source | Behavior |
| :---- | :---- | :---- |
| Template Name | template.name | Clickable; opens the template for editing. Sortable. Primary identifier. |
| Type | template.type | Scheduled / Reminder / Unscheduled. |
| Txn Type | template.txn\_type | Bill in v1. Reserved for future types. |
| Interval | derived from schedule | Human-readable summary, e.g., “Every Month”. Blank for Unscheduled. |
| Previous Date | template.previous\_run\_date | Date of the last generated bill/reminder; blank until first run. |
| Next Date | template.next\_run\_date | Next due date; blank for Unscheduled and Ended templates. |
| Vendor | vendor.display\_name | The payee. Clickable to the vendor record. Sortable. |
| Amount | template total | Sum of all lines \+ tax, in base currency. Right-aligned. Sortable. |
| Action | — | Row menu: Edit (default) plus Use, Duplicate, Delete. |

### **9.1.2 Toolbar & controls**

* **Filter by Name** — live, case-insensitive, partial-match text filter.

* **Filter** — opens filter options (transaction type, template type); the current filter label (e.g., “All”) is shown beside it.

* **New** — opens the Select Transaction Type dialog (Section 9.2).

* **View switcher** — toggles between the Recurring Transactions view and the Reminder List view.

* **Manage recurring payments** — link to payment-method management (related to Autopay; gated by availability).

* **Print / Settings (gear)** — print the list and choose which columns are visible.

### **9.1.3 States**

| State | Presentation |
| :---- | :---- |
| Empty | No templates exist → friendly empty state explaining recurring transactions with a prominent New button. |
| Populated | Table of templates with sorting and pagination. |
| Filtered — no match | “No recurring transactions match your filter.” with a clear-filter affordance. |
| Loading | Skeleton rows while data loads. |

## **9.2 New → Select Transaction Type**

Because the Recurring Transactions list is designed to hold multiple transaction types over time, creating a new template starts by asking which type to build. In v1 the only option is Bill, but the dialog is retained so the flow is identical when more types are added.

| Field | Control | Required | Behavior / Rules |
| :---- | :---- | :---- | :---- |
| Transaction Type | Dropdown | **Yes** | Options are the transaction types that support recurring templates. v1: Bill (default selected). |
| OK | Button | — | Opens the recurring template form for the chosen type. |
| Cancel / ✕ | Button | — | Closes the dialog; returns to the list with no changes. |

## **9.3 Recurring Bill template form**

This is the core screen where a template is defined. It closely mirrors the standard one-off Bill screen so users feel at home, with an added “Recurring Bill” configuration band at the top (template name, type, and schedule) and a “Save template” action instead of “Save”. The body of the form — vendor, category lines, item lines, memo, attachments, totals — behaves exactly like the normal Bill screen and reuses the same components and validations.

### **9.3.1 Header — template name & type**

| Field | Control | Required | Behavior / Rules |
| :---- | :---- | :---- | :---- |
| Template name | Text | **Yes** | Human label shown throughout the list and reminders. Must be unique within the company (case-insensitive). Max 100 chars. |
| Type | Dropdown | **Yes** | Scheduled / Reminder / Unscheduled. Changing it shows/hides the schedule fields and the advance/remind field (see 9.3.2–9.3.4). Default: Scheduled. |
| Create \_\_ days in advance | Number | Cond. | Shown only when Type \= Scheduled. Integer 0–90. How many days before Next Date the bill is created. 0 \= create on the date itself. |
| Remind \_\_ days before the transaction date | Number | Cond. | Shown only when Type \= Reminder. Integer 0–90. How many days before the date the reminder appears. |

### **9.3.2 Behavior — Type \= Scheduled**

When Scheduled is selected, the form shows the “Create \_\_ days in advance” field and the full Interval \+ Start date \+ End block. On save, the template is active and the Generation Job will create bills automatically. This is the default and covers the most common case (fixed, unchanging bills).

| Example “Create 3 days in advance”, Monthly on the 1st, means a bill dated the 1st is actually created and posted on the 29th/30th of the prior month, giving the user three days of lead time in payables before the bill's date. |
| :---- |

### **9.3.3 Behavior — Type \= Reminder**

When Reminder is selected, the “days in advance” field is replaced by “Remind \_\_ days before the transaction date”. The Interval \+ Start date \+ End block still appears (a reminder needs a schedule to know when to remind), but no bill is ever created automatically. Instead, on the reminder date the system raises a reminder item and notifies the user, who then reviews, edits, and creates the bill.

### **9.3.4 Behavior — Type \= Unscheduled**

When Unscheduled is selected, the interval, start date, end, and advance/remind fields are all hidden, and a short note explains: “Unscheduled transactions don't have timetables; you use them as needed from the Recurring Transactions list.” The template simply stores the bill definition for on-demand use via the Use action.

### **9.3.5 Vendor, mailing address & terms**

| Field | Control | Required | Behavior / Rules |
| :---- | :---- | :---- | :---- |
| Vendor | Searchable dropdown | **Yes** | Select from the Vendor master. Selecting a vendor auto-fills Mailing address and default Terms. A new vendor can be created inline. |
| Mailing address | Multiline text | No | Pre-filled from the vendor; editable per template. |
| Terms | Dropdown | No | Payment terms (e.g., Net 15). Used to derive the due date on each generated bill from its bill date. |

### **9.3.6 Interval configuration (the frequency engine)**

Shown for Scheduled and Reminder templates. This block defines how often the template repeats. It is composed of a frequency selector, a day selector, and an “every N periods” multiplier, which together express rules from “every day” to “every 3 months on the 15th”.

| Control | Options | Behavior / Rules |
| :---- | :---- | :---- |
| Frequency | Daily, Weekly, Monthly, Yearly | Sets the base cadence and which secondary controls appear. |
| Day selector (mode) | “day” or “weekday” | Monthly/Yearly can repeat on a day-of-month (e.g., the 15th) or a weekday-of-month (e.g., the first Monday). |
| Ordinal / day value | 1st…31st, or first/second/…/last | The specific day-of-month or the ordinal for a weekday rule. |
| Every N periods | Integer ≥ 1 | Multiplier on the frequency: every 1 month, every 2 weeks, every 3 months, etc. |

Frequency-specific behavior:

* **Daily** — repeats every N days from the start date.

* **Weekly** — repeats every N weeks on a chosen weekday (or weekdays).

* **Monthly** — every N months, either on a day-of-month (1–31) or an ordinal weekday (e.g., last Friday). Day 29–31 clamps to the last valid day in shorter months.

* **Yearly** — every N years on a specific month \+ day (or ordinal weekday).

### **9.3.7 Start date, End condition & Autopay**

| Field | Control | Required | Behavior / Rules |
| :---- | :---- | :---- | :---- |
| Start date | Date (MM/DD/YYYY) | **Yes\*** | First date the schedule considers. \*Required for Scheduled/Reminder. The first Next Date is the first scheduled occurrence on or after this date. |
| End | Dropdown | **Yes\*** | None (never ends), By (a specific end date), or After (a fixed number of occurrences). Selecting By/After reveals the corresponding input. |
| End date | Date | Cond. | Shown when End \= By. No occurrence is generated after this date. |
| Occurrences | Number | Cond. | Shown when End \= After. Generation stops once this many bills/reminders have been produced. |

#### **Autopay**

An Autopay section lets a user opt to pay each generated bill automatically through a connected payment method. In v1 this control is present but gated: when payments are unavailable, the section shows an informational message (“Autopay isn't available right now. You can save the recurring bill now and turn on autopay later.”) and the template still saves normally. Autopay execution itself is out of scope for v1 (see Section 5.2); the setting is stored so it can be honored once payment execution ships.

### **9.3.8 Category details (account-based lines)**

Category lines post amounts directly to general-ledger accounts (expenses or assets). This is used when a bill is not tied to a catalog product — for example, rent or a service fee. Behavior is identical to the standard Bill screen.

| Column | Control | Behavior / Rules |
| :---- | :---- | :---- |
| \# | Row number | Auto; supports drag-to-reorder. |
| Category | Account dropdown | Required per line. From the Chart of Accounts (expense/asset). |
| Description | Text | Optional free text; carried onto generated bills. |
| Amount | Currency | Line amount; feeds the Total. |
| Billable | Checkbox | Marks the cost as billable to a customer. |
| Tax | Tax code | Line tax; computed by the tax engine. |
| Customer | Dropdown | Customer to associate/bill the line to (for billable costs and job tracking). |

Add lines / Clear all lines controls add or reset rows. Empty lines are ignored on save.

### **9.3.9 Item details (product/service lines)**

Item lines reference catalog products/services and are used when the bill maps to specific purchased items. Selecting a product auto-fills its description, rate, and account; Qty × Rate computes the line Amount.

| Column | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Product/Service | Item dropdown | From Products & Services; auto-fills description, rate, and the linked account. |
| Description | Text | Defaults from the item; editable. |
| Qty | Number | Quantity purchased; drives Amount. |
| Rate | Currency | Unit price; defaults from the item. |
| Amount | Currency | Qty × Rate (auto). |
| Billable / Tax / Customer | Controls | Same meaning as on category lines. |

### **9.3.10 Totals, memo & attachments**

* **Total** — a live sum of all category and item lines plus tax, shown in base currency. Must always equal the sum of line amounts \+ computed tax.

* **Memo** — free-text note stored on the template and copied to each generated bill.

* **Attachments** — a single file up to 20 MB may be attached to the template for reference. Per market convention, the attachment is NOT automatically copied onto each generated bill; this is documented so behavior is not mistaken for a bug.

### **9.3.11 Save / Cancel**

* **Save template** — validates the form, persists the template, and (for Scheduled/Reminder) computes the first Next Date. Returns to the list with a success confirmation.

* **Cancel** — discards unsaved changes after a confirmation prompt if the form is dirty.

## **9.4 Row actions (Edit / Use / Duplicate / Delete)**

Each template row exposes an Action menu. Edit is the default (visible) action; the caret reveals Use, Duplicate, and Delete.

| Action | Behavior |
| :---- | :---- |
| **Edit** | Opens the template pre-filled. Saving recalculates Next Date if the schedule changed. Never alters already-generated bills. |
| **Use** | Creates a bill from the template now. For Scheduled/Reminder it opens a pre-filled, editable bill; for Unscheduled it is the primary way to produce a bill. The result posts to payables and links back to the template. |
| **Duplicate** | Creates an independent copy named “Copy of …”, pre-filled with every field, with empty run history. |
| **Delete** | Confirms, then soft-deletes the template. Future generation stops; previously generated bills remain. Logged to audit. |

## **9.5 Reminders List**

The Reminders List is a focused queue for Reminder-type templates whose reminder date has arrived. It is where Marcus does his daily/weekly work. It is reachable from the Recurring Transactions view switcher and via notifications.

### **9.5.1 Columns & controls**

| Element | Behavior |
| :---- | :---- |
| Find by name | Case-insensitive partial filter on template name. |
| Transaction type filter | Narrows to a transaction type (Bill in v1). |
| Columns | Template Name, Txn Type, Interval, Txn Date, Amount, Vendor, and an Action to create the bill. |
| Batch actions | Select multiple reminders and create their bills in one operation. |
| Empty state | “There are no recurring reminder transactions matching the criteria.” |

### **9.5.2 Behavior**

* An item appears here on its reminder date (transaction date minus “remind days before”).

* Creating the bill from a reminder opens the pre-filled bill so the user can adjust the amount before posting.

* Once the bill is created, the reminder item is cleared, and the template's Previous/Next dates advance to the following occurrence.

* Reminders that are skipped remain until acted upon or until their occurrence is superseded, per the catch-up rules in Section 11\.

## **9.6 “Make recurring” from an existing bill**

As a convenience, a user editing a normal one-off bill can convert it into a template without re-entering anything. Selecting “Make recurring” on a bill copies its vendor, lines, amounts, and memo into a new recurring template and adds the Recurring Bill configuration band (name, type, schedule). The user completes the schedule and saves. The original bill is unaffected; the new template begins its own lifecycle.

# **10\. User Flows**

The flows below trace the main journeys end to end. Each is a step table showing the actor, the action, and the system's response, so both frontend and backend behavior are explicit. “User” \= the person in the app; “System” \= Balanzify (UI or background job).

## **10.1 Flow — Create a Scheduled recurring bill**

| \# | Actor | Action | System response |
| :---- | :---- | :---- | :---- |
| 1 | User | Opens Recurring Transactions and clicks New. | Shows Select Transaction Type dialog with Bill preselected. |
| 2 | User | Confirms Bill. | Opens the recurring bill template form (Type defaults to Scheduled). |
| 3 | User | Enters template name, keeps Scheduled, sets days-in-advance. | Shows Interval \+ Start date \+ End block. |
| 4 | User | Selects vendor. | Auto-fills mailing address and default terms. |
| 5 | User | Adds category/item lines and amounts. | Updates the live Total (lines \+ tax). |
| 6 | User | Sets interval, start date, end condition. | Validates the schedule inputs inline. |
| 7 | User | Clicks Save template. | Validates, persists template, computes first Next Date, returns to list with confirmation. |
| 8 | System | On the due date (minus days-in-advance), the job runs. | Creates a real bill, links it to the template, advances Previous/Next dates. |

## **10.2 Flow — Automatic generation (background)**

| \# | Actor | Action | System response |
| :---- | :---- | :---- | :---- |
| 1 | System | Generation Job triggers at the org's run time. | Loads active Scheduled/Reminder templates whose effective due date ≤ today. |
| 2 | System | For each due Scheduled template… | Builds a bill from the template snapshot, applies terms → due date, posts it to AP. |
| 3 | System | Records the generation. | Creates a template→bill link; writes an audit entry; advances Previous/Next dates. |
| 4 | System | For each due Reminder template… | Creates a reminder item, sends a notification. Does NOT create a bill. |
| 5 | System | Handles end conditions. | If the occurrence was the last (by date or count), marks the template Ended. |
| 6 | System | Completes the run. | Emits metrics (processed, skipped, failed) for monitoring. |

## **10.3 Flow — Reminder template, then process the reminder**

| \# | Actor | Action | System response |
| :---- | :---- | :---- | :---- |
| 1 | User | Creates a template with Type \= Reminder, sets remind-days-before. | Saves; computes Next Date; no bill created. |
| 2 | System | On (txn date − remind days), the job runs. | Adds an item to the Reminders List; sends a notification. |
| 3 | User | Opens the Reminders List and selects the item. | Opens a pre-filled bill for review. |
| 4 | User | Adjusts the amount (e.g., this month's utility total) and creates the bill. | Posts the bill to AP, links it to the template. |
| 5 | System | Clears the reminder; advances the schedule. | Previous Date \= this occurrence; Next Date \= next occurrence. |

## **10.4 Flow — Use an Unscheduled template on demand**

| \# | Actor | Action | System response |
| :---- | :---- | :---- | :---- |
| 1 | User | Finds the Unscheduled template in the list. | Row shows no Next Date. |
| 2 | User | Opens Action → Use. | Opens a pre-filled, editable bill built from the template. |
| 3 | User | Tweaks lines if needed and saves the bill. | Posts the bill to AP, links it to the template. |
| 4 | System | Records the usage. | Writes audit entry; template remains available for future use. |

## **10.5 Flow — Edit a template (safely)**

| \# | Actor | Action | System response |
| :---- | :---- | :---- | :---- |
| 1 | User | Action → Edit on a template. | Opens the form pre-filled with current values. |
| 2 | User | Changes amount / account / schedule. | Validates inline. |
| 3 | User | Saves. | Persists changes; if schedule changed, recomputes Next Date. Already-generated bills are untouched. |
| 4 | System | If a shared item/vendor changed elsewhere… | Informs the user how it affects this and other templates (update-all vs. one-time semantics). |

## **10.6 Flow — Delete a template**

| \# | Actor | Action | System response |
| :---- | :---- | :---- | :---- |
| 1 | User | Action → Delete. | Shows a confirmation warning that future generation will stop. |
| 2 | User | Confirms. | Soft-deletes the template; stops all future generation immediately. |
| 3 | System | Preserves history. | Previously generated bills remain in the ledger; template→bill links and audit entries survive. |

# **11\. Business Rules & Scheduling Engine**

This is the engineering heart of the feature. It specifies precisely how dates are calculated, how bills are generated, and how the system stays correct under delays, retries, and edge conditions. The rules here are the contract the backend must implement and QA must verify.

## **11.1 Computing the Next Date**

The Next Date is the next occurrence produced by the schedule rule on or after a reference date (the start date for a brand-new template, or the last occurrence \+ one interval thereafter). The algorithm:

1. Determine the anchor: for a new template, anchor \= start date; otherwise anchor \= previous occurrence date.

2. Add one interval step to the anchor based on frequency × “every N”: N days, N weeks (to the chosen weekday), N months (to the chosen day-of-month or ordinal weekday), or N years.

3. Apply month-end clamping (Section 11.2).

4. If the computed date is before today and the template is new (back-dated start), roll forward to the first future occurrence unless catch-up is required (Section 11.6).

5. If the computed date exceeds the end condition, return none and mark the template Ended.

## **11.2 Month-end clamping**

Monthly and yearly rules set to a day that does not exist in a given month must fall back to the last valid day of that month. This matches every mature accounting platform and user expectation.

| Rule | Month | Resulting date |
| :---- | :---- | :---- |
| Monthly on the 31st | February (non-leap) | Feb 28 |
| Monthly on the 31st | February (leap) | Feb 29 |
| Monthly on the 31st | April | Apr 30 |
| Monthly on the 30th | February | Feb 28 / 29 |
| Yearly on Feb 29 | Non-leap year | Feb 28 |
| **Rule** Clamping never changes the underlying rule. A template set to the 31st that produced Feb 28 still produces Mar 31 next — the clamp applies per month, it does not permanently move the day-of-month. |  |  |

## **11.3 Days-in-advance creation (Scheduled)**

For Scheduled templates, the bill's date is the scheduled occurrence date, but the bill is actually created earlier by the “Create \_\_ days in advance” value. Formally:

| Advance-creation formula bill\_date        \= occurrence\_date creation\_trigger \= occurrence\_date − create\_days\_in\_advance due\_date         \= bill\_date \+ terms(net\_days) The Generation Job creates the bill on the first run where today \>= creation\_trigger, dating the bill occurrence\_date. |
| :---- |

This gives users lead time: the bill shows up in payables a few days before its official date, so it can be scheduled for payment without being late.

## **11.4 Reminder timing (Reminder)**

For Reminder templates, no bill is created. Instead the reminder surfaces on:

| Reminder formula reminder\_date \= occurrence\_date − remind\_days\_before On the first job run where today \>= reminder\_date, the system raises a reminder item and sends a notification. The user must act to create the bill; the schedule advances only once a bill is created (or the occurrence is explicitly superseded). |
| :---- |

## **11.5 End conditions**

| End \=  | Rule |
| :---- | :---- |
| **None** | The schedule never ends; Next Date always advances to the following occurrence. |
| **By (date)** | No occurrence with a date after the end date is produced. Once the last valid occurrence is processed, the template is marked Ended. |
| **After (N)** | A running occurrence counter increments on each generated bill/reminder. When it reaches N, the template is marked Ended and produces nothing further. |

## **11.6 The Generation Job**

A background worker drives all automatic behavior. Its correctness properties matter more than its exact scheduling technology (cron, queue, or scheduler service).

### **11.6.1 Cadence & timezone**

* Runs at least once per day at the company's configured local time (e.g., early morning), so “today” is evaluated in the org's timezone, not UTC.

* May run more frequently; correctness must not depend on run frequency (idempotency below).

### **11.6.2 Selection query**

* Selects active (not ended, not deleted) Scheduled and Reminder templates whose effective trigger date (creation\_trigger for Scheduled, reminder\_date for Reminder) is on or before today, and which have not already produced the current occurrence.

### **11.6.3 Idempotency (no duplicates)**

* **Occurrence key.** Each occurrence is identified by (template\_id, occurrence\_date). Before creating a bill/reminder, the job checks whether that occurrence key already exists; if so it skips. This guarantees exactly-once generation even if the job runs multiple times or restarts mid-run.

* **Transactional write.** The generated bill, the template→bill link, the occurrence record, and the advance of Previous/Next dates are written atomically. A failure rolls back the whole occurrence so it is retried cleanly.

### **11.6.4 Catch-up after downtime**

* If the job was down and multiple occurrences are now overdue, the default is to generate the missed occurrences in order (so the ledger is complete), each with its correct historical date, still respecting the end condition.

* A configurable safeguard can cap catch-up (e.g., collapse to the latest occurrence) to avoid a flood after long outages; the default is full catch-up for accounting completeness.

### **11.6.5 Failure handling**

* A failed occurrence (e.g., a referenced account was deleted) is logged, surfaced to the user as a fixable error, and retried on the next run; it does not block other templates.

* Per-run metrics (processed / skipped / failed) are emitted for monitoring and alerting.

## **11.7 What a generated bill inherits from the template**

When a bill is generated, it is a point-in-time snapshot of the template as it exists at generation. Subsequent template edits do not change it.

| Inherited | Notes |
| :---- | :---- |
| Vendor & mailing address | Copied as-is. |
| Category & item lines | All lines, descriptions, amounts, qty/rate, accounts, tax codes, billable flags, customer links. |
| Terms → due date | Due date computed from bill date \+ terms at generation time. |
| Memo | Copied to the bill. |
| Bill number | Assigned by the standard bill-numbering sequence, not the template. |
| Attachment | NOT copied (documented convention). |
| Autopay preference | Stored on the bill; honored once payment execution ships. |

## **11.8 Concurrency & ordering**

* Occurrences for a single template are produced in chronological order.

* Two job instances must not process the same occurrence; a lock or the occurrence-key uniqueness constraint prevents double-creation.

* Editing a template while the job runs is safe: the job snapshots the template row it read; the next occurrence uses the updated values.

# **12\. Data Model**

This section defines the persistent entities behind the feature. It is written database-agnostically; types are indicative (use the platform's native equivalents). All tables are tenant-scoped by company\_id and use soft deletes so history and audit links survive. Money fields use a fixed-precision decimal, never floating point.

## **12.1 Entities & relationships**

Four new entities plus two new columns on the existing Bill entity:

* **recurring\_template** — the parent blueprint (1 per repeating bill).

* **recurring\_template\_line** — the category and item lines of a template (many per template).

* **recurring\_schedule** — the frequency rule and start/end condition (1 per template; may be embedded as columns or a JSON value object).

* **recurring\_occurrence** — the run log and idempotency record (one row per produced occurrence); also powers the Reminders List.

* **bill.source\_template\_id / bill.source\_occurrence\_id** — new nullable columns linking a generated bill back to its template and occurrence.

| Relationship | Cardinality | Meaning |
| :---- | :---- | :---- |
| template → lines | 1 : N | A template has many category/item lines. |
| template → schedule | 1 : 1 | A template has one schedule (null for Unscheduled). |
| template → occurrences | 1 : N | A template produces many occurrences over time. |
| occurrence → bill | 1 : 0..1 | A Scheduled occurrence produces one bill; a Reminder occurrence may produce one once the user acts. |
| template → vendor | N : 1 | Many templates can reference the same vendor. |
| line → account / item / tax / customer | N : 1 | Lines reference existing masters. |

## **12.2 recurring\_template**

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Primary key. |
| company\_id | UUID (FK) | No | Tenant scope. |
| name | varchar(100) | No | Template name; unique per company (case-insensitive). |
| txn\_type | enum | No | Transaction type. v1: bill. |
| template\_type | enum | No | scheduled | reminder | unscheduled. |
| status | enum | No | active | ended | deleted. |
| vendor\_id | UUID (FK) | No | Payee (Vendor master). |
| mailing\_address | text | Yes | Copied from vendor; editable. |
| terms\_id | UUID (FK) | Yes | Payment terms; drives generated due dates. |
| memo | text | Yes | Note copied to generated bills. |
| attachment\_id | UUID (FK) | Yes | Reference file on the template (not copied to bills). |
| autopay\_enabled | boolean | No | Default false; honored once payment execution ships. |
| create\_days\_in\_advance | int | Yes | Scheduled only; 0–90. |
| remind\_days\_before | int | Yes | Reminder only; 0–90. |
| currency\_code | char(3) | No | Base/txn currency. |
| total\_amount | decimal(19,4) | No | Cached sum of lines \+ tax; recomputed on save. |
| previous\_run\_date | date | Yes | Last occurrence date; null until first run. |
| next\_run\_date | date | Yes | Next occurrence; null for Unscheduled/Ended. |
| occurrences\_generated | int | No | Counter for End \= After N. |
| created\_by | UUID | No | Author. |
| created\_at / updated\_at | timestamptz | No | Audit timestamps. |
| deleted\_at | timestamptz | Yes | Soft-delete marker. |

## **12.3 recurring\_schedule (fields / value object)**

Stored per template (columns or JSON). Null for Unscheduled templates.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| frequency | enum | Yes | daily | weekly | monthly | yearly. |
| interval\_count | int | No | “Every N” multiplier; ≥ 1\. |
| day\_mode | enum | Yes | day\_of\_month | weekday (for monthly/yearly). |
| day\_of\_month | int | Yes | 1–31 (clamped to month end). |
| weekday | enum / set | Yes | mon…sun (weekly may allow multiple). |
| ordinal | enum | Yes | first | second | third | fourth | last (weekday-of-month). |
| month\_of\_year | int | Yes | 1–12 (yearly). |
| start\_date | date | No\* | First date considered (\*required for scheduled/reminder). |
| end\_type | enum | No | none | by\_date | after\_count. |
| end\_date | date | Yes | Required when end\_type \= by\_date. |
| end\_after\_occurrences | int | Yes | Required when end\_type \= after\_count. |

## **12.4 recurring\_template\_line**

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Primary key. |
| template\_id | UUID (FK) | No | Parent template. |
| line\_type | enum | No | category | item. |
| position | int | No | Display/order index. |
| account\_id | UUID (FK) | Yes | Category lines: expense/asset account. |
| item\_id | UUID (FK) | Yes | Item lines: product/service. |
| description | text | Yes | Line description. |
| quantity | decimal(19,4) | Yes | Item lines. |
| rate | decimal(19,4) | Yes | Item lines unit price. |
| amount | decimal(19,4) | No | Line amount (Qty × Rate for items). |
| is\_billable | boolean | No | Billable-to-customer flag. |
| tax\_code\_id | UUID (FK) | Yes | Line tax code. |
| customer\_id | UUID (FK) | Yes | Associated customer (billable/job tracking). |

## **12.5 recurring\_occurrence (run log & reminders)**

One row per occurrence the engine produces. The uniqueness constraint on (template\_id, occurrence\_date) is what guarantees exactly-once generation. Rows with status \= reminded and resolved\_at IS NULL are exactly the Reminders List.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Primary key. |
| template\_id | UUID (FK) | No | Parent template. |
| occurrence\_date | date | No | The scheduled date of this occurrence. |
| status | enum | No | generated | reminded | skipped | failed. |
| generated\_bill\_id | UUID (FK) | Yes | The bill created for this occurrence, if any. |
| reminded\_at | timestamptz | Yes | When a reminder was raised. |
| resolved\_at | timestamptz | Yes | When the user created the bill / cleared the reminder. |
| error\_detail | text | Yes | Reason a failed occurrence did not generate. |
| created\_at | timestamptz | No | Row creation. |
| — | UNIQUE | — | unique(template\_id, occurrence\_date) — idempotency key. |

## **12.6 New columns on the Bill entity**

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| source\_template\_id | UUID (FK) | Yes | The template that generated this bill (null for manual bills). |
| source\_occurrence\_id | UUID (FK) | Yes | The specific occurrence that produced this bill. |

## **12.7 Sample template (JSON)**

| {   "id": "tmpl\_9f3a...",   "company\_id": "co\_1122...",   "name": "Monthly Building Lease",   "txn\_type": "bill",   "template\_type": "scheduled",   "status": "active",   "vendor\_id": "ven\_hall...",   "terms\_id": "terms\_net15",   "create\_days\_in\_advance": 0,   "currency\_code": "USD",   "schedule": {     "frequency": "monthly", "interval\_count": 1,     "day\_mode": "day\_of\_month", "day\_of\_month": 1,     "start\_date": "2026-07-01", "end\_type": "none"   },   "lines": \[     { "line\_type": "category", "account\_id": "acct\_rent",       "description": "Office rent", "amount": 900.00,       "is\_billable": false, "tax\_code\_id": null }   \],   "total\_amount": 900.00,   "previous\_run\_date": null,   "next\_run\_date": "2026-07-01" } |
| :---- |

# **13\. API Specification**

A REST API backs both the UI and any integrations. All endpoints are tenant-scoped (company inferred from auth), require authentication, and enforce the permissions in Section 16\. Requests and responses are JSON. Timestamps are ISO-8601; dates are YYYY-MM-DD in the company timezone.

## **13.1 Endpoint summary**

| Endpoint | Method | Purpose |
| :---- | :---- | :---- |
| /api/v1/recurring-templates | GET | List templates (filter, sort, paginate). |
| /api/v1/recurring-templates | POST | Create a template. |
| /api/v1/recurring-templates/{id} | GET | Retrieve one template with lines and schedule. |
| /api/v1/recurring-templates/{id} | PUT | Update a template (recomputes Next Date). |
| /api/v1/recurring-templates/{id} | DELETE | Soft-delete (stops future generation). |
| /api/v1/recurring-templates/{id}:duplicate | POST | Duplicate a template. |
| /api/v1/recurring-templates/{id}:use | POST | Generate a bill now from the template. |
| /api/v1/recurring-reminders | GET | List due reminder occurrences. |
| /api/v1/recurring-reminders/{occId}:create-bill | POST | Create a bill from a reminder occurrence. |
| /internal/recurring/run | POST | Trigger the Generation Job (cron/admin only). |

## **13.2 List templates**

**Request:** GET /api/v1/recurring-templates?q=lease\&template\_type=scheduled\&sort=next\_run\_date\&order=asc\&page=1\&page\_size=25

Query params: q (name search), txn\_type, template\_type, status, sort (name | next\_run\_date | vendor | amount), order, page, page\_size.

| Response 200 OK {   "data": \[     {       "id": "tmpl\_9f3a...", "name": "Monthly Building Lease",       "template\_type": "scheduled", "txn\_type": "bill",       "interval\_label": "Every Month",       "previous\_run\_date": null, "next\_run\_date": "2026-07-01",       "vendor": { "id": "ven\_hall...", "name": "Hall Properties" },       "amount": 900.00, "currency\_code": "USD", "status": "active"     }   \],   "page": 1, "page\_size": 25, "total": 2 } |
| :---- |

## **13.3 Create template**

**Request:** POST /api/v1/recurring-templates

| Body {   "name": "Telephone Bill",   "txn\_type": "bill",   "template\_type": "reminder",   "vendor\_id": "ven\_caltel...",   "terms\_id": "terms\_net30",   "remind\_days\_before": 5,   "schedule": {     "frequency": "monthly", "interval\_count": 1,     "day\_mode": "day\_of\_month", "day\_of\_month": 19,     "start\_date": "2026-07-19", "end\_type": "none"   },   "lines": \[     { "line\_type": "category", "account\_id": "acct\_utilities",       "description": "Monthly phone", "amount": 74.36 }   \],   "memo": "Varies monthly" } |
| :---- |
| **Response** 201 Created  → returns the full template (see 12.7), with server-computed next\_run\_date and total\_amount. 422 Unprocessable Entity  → validation errors, e.g.: { "errors": \[    { "field": "schedule.start\_date",      "code": "required\_for\_scheduled\_or\_reminder" },    { "field": "name", "code": "duplicate\_name" } \] } |

## **13.4 Use a template now**

**Request:** POST /api/v1/recurring-templates/{id}:use

Body may include a mode flag: draft (return an editable bill payload without posting) or post (create the bill immediately). Default: draft for Reminder/Unscheduled, post for Scheduled. Returns the created or draft bill, linked via source\_template\_id.

## **13.5 List & resolve reminders**

| Reminders API GET /api/v1/recurring-reminders?q=phone\&txn\_type=bill 200 OK → occurrences with status=reminded, resolved\_at=null: { "data": \[ {    "occurrence\_id": "occ\_77...", "template\_id": "tmpl\_tel...",    "template\_name": "Telephone Bill", "txn\_type": "bill",    "interval\_label": "Every Month", "txn\_date": "2026-07-19",    "amount": 74.36, "vendor": { "name": "Cal Telephone" } } \] } POST /api/v1/recurring-reminders/occ\_77...:create-bill Body: { "overrides": { "lines": \[ { "amount": 81.10 } \] } } 201 Created → posts the bill, sets occurrence.resolved\_at, advances the template schedule. |
| :---- |

## **13.6 Standard error model**

| HTTP | Code | Meaning |
| :---- | :---- | :---- |
| 400 | bad\_request | Malformed JSON or params. |
| 401 | unauthorized | Missing/invalid auth. |
| 403 | forbidden | User lacks the required permission (Section 16). |
| 404 | not\_found | Template/occurrence not found in this company. |
| 409 | conflict | Concurrent update or duplicate occurrence. |
| 422 | validation\_error | Field-level validation failures (array of {field, code}). |
| 500 | internal\_error | Unexpected server error; safe to retry idempotent calls. |

# **14\. Integration with Other Modules**

Recurring Transactions is not a standalone silo — it is deliberately thin, reusing the accounting primitives Balanzify already has. This section describes exactly how it connects to each existing module, which direction data flows, and the nature of the coupling. Reusing these services (rather than duplicating them) is what keeps generated bills indistinguishable from manual bills.

| Module | Direction | How they connect |
| :---- | :---- | :---- |
| **Vendor master** | Read | A template references a vendor\_id. Selecting a vendor pulls its mailing address and default terms. Generated bills carry the vendor exactly as a manual bill would. |
| **Chart of Accounts** | Read | Category lines post to expense/asset accounts; the AP control account is used when the bill is created. If a referenced account is later archived, the template flags an error on next generation (Section 15). |
| **Products & Services** | Read | Item lines reference catalog items and inherit their description, rate, and linked account at generation time. |
| **Tax engine** | Read / compute | Line tax codes are resolved and totals computed by the existing tax service, so recurring bills tax identically to manual ones. |
| **Terms / payment terms** | Read | The template's terms drive each generated bill's due date (bill\_date \+ net days). |
| **Bill / AP ledger** | Write | Generated bills are created through the same Bill service and validations as manual bills, then appear in payables, aging, and the GL. New source\_template\_id / source\_occurrence\_id columns preserve the link. |
| **Sales / Expense modules** | Shared engine | The list, template form, scheduler, and occurrence log are built generically so recurring invoices/expenses can reuse them later by adding a txn\_type — no re-architecture. |
| **Attachments / file store** | Read | A template can hold one attachment reference (not copied to children). |
| **Notifications** | Write | Reminder items and (optionally) generation summaries are delivered through the platform notification service. |
| **Audit log** | Write | Template create/edit/delete and every generated bill are recorded for traceability and support. |
| **Reporting** | Read | A Recurring Templates report lists templates grouped by type; generated bills flow into all standard AP and expense reports automatically. |

| Why generated bills must go through the Bill service If recurring bills were written straight to the database, they would bypass numbering, tax, validation, and posting logic and quickly drift from manual bills. Routing every generation through the existing Bill service guarantees one source of truth for what a valid bill is. |
| :---- |

# **15\. Edge Cases, Validation & Error Handling**

## **15.1 Field validation rules**

| Field | Rule |
| :---- | :---- |
| Template name | Required; 1–100 chars; unique per company (case-insensitive); trimmed. |
| Template type | Required; one of scheduled/reminder/unscheduled. |
| Vendor | Required; must be an active vendor in the company. |
| Create days in advance | Required when Scheduled; integer 0–90. |
| Remind days before | Required when Reminder; integer 0–90. |
| Frequency / interval | Required when Scheduled/Reminder; interval\_count ≥ 1; day/ordinal consistent with frequency. |
| Start date | Required when Scheduled/Reminder; must be a valid date. |
| End date | Required when End \= By; must be ≥ start date. |
| Occurrences | Required when End \= After; integer ≥ 1\. |
| Lines | At least one non-empty category or item line; each line amount is a valid decimal; item lines need Qty and Rate. |
| Total | Must equal Σ line amounts \+ computed tax. |
| Attachment | Optional; single file ≤ 20 MB; allowed file types only. |

## **15.2 Behavioral edge cases**

| Scenario | Expected behavior |
| :---- | :---- |
| Monthly on 31st in a short month | Clamp to the last valid day (Feb 28/29, Apr 30). Rule unchanged for future months. |
| Back-dated start date | New template rolls forward to the first future occurrence by default; catch-up applies only where explicitly configured for accounting completeness. |
| Generation job was down for days | On recovery, missed occurrences are generated in date order with their correct historical dates; idempotency prevents duplicates. |
| Job runs twice in one day | The (template\_id, occurrence\_date) unique key makes the second run skip already-produced occurrences. |
| Referenced account/item archived | Generation for that occurrence fails gracefully, is logged with a fixable error, surfaced to the user, and retried next run; other templates are unaffected. |
| Vendor deleted after template created | Template flags an error and pauses generation until a valid vendor is set; existing bills remain. |
| User edits template mid-cycle | Change applies to future occurrences only; already-generated bills are untouched; Next Date recomputed if schedule changed. |
| Template deleted with future schedule | Future generation stops immediately; past bills remain; template soft-deleted so links/audit survive. |
| End \= After N reached | Template marked Ended; Next Date cleared; no further generation. |
| Reminder never acted upon | Reminder stays in the list until resolved or its occurrence is superseded per catch-up rules; no bill is created automatically. |
| Duplicate of a running template | Copy is independent with empty run history and its own schedule; original unaffected. |
| Autopay toggled on while payments unavailable | Preference is stored; an informational message explains autopay will apply once available; the bill still generates. |
| Timezone near midnight / DST change | “Today” is evaluated in the company timezone; DST shifts do not skip or duplicate an occurrence. |
| Zero-amount or empty lines | Empty lines are ignored; a template with no valid line fails validation. |

## **15.3 Error-handling principles**

* **Fail safe, not silent.** A generation error never posts a bad bill; it records a failed occurrence and tells the user what to fix.

* **Isolate failures.** One template's problem must not stop the whole job; each occurrence is processed independently.

* **Idempotent retries.** Any retried generation is safe because of the occurrence uniqueness key.

* **Actionable messages.** Errors name the offending field/reference (e.g., “Account ‘Rent’ was archived”), not a generic failure.

* **Observable.** Every run emits counts and every failure is logged and alertable.

# **16\. Permissions & Roles**

Recurring templates create real financial obligations, so access follows the same role model as manual bills. The matrix below is indicative and should map onto Balanzify's existing roles; the key rule is that anyone who can create a bill can create a recurring bill, and template management aligns with bill management.

| Capability | Admin | Accountant | Bookkeeper | AP Clerk | Viewer |
| :---- | :---- | :---- | :---- | :---- | :---- |
| View templates & reminders | ✔ | ✔ | ✔ | ✔ | ✔ |
| Create / edit templates | ✔ | ✔ | ✔ | ✔ | — |
| Delete templates | ✔ | ✔ | ✔ | — | — |
| Use / create bill from template | ✔ | ✔ | ✔ | ✔ | — |
| Process reminders | ✔ | ✔ | ✔ | ✔ | — |
| Configure autopay | ✔ | ✔ | — | — | — |

All endpoints enforce these permissions server-side; the UI hides or disables actions the current role cannot perform.

# **17\. Non-Functional Requirements**

Functional correctness is necessary but not sufficient. Because recurring transactions run unattended and post financial records, the module is held to explicit quality bars for performance, reliability, security, and correctness across time zones. Each requirement below is written so QA can turn it into a measurable test.

## **17.1 Performance**

| Area | Requirement | Target |
| :---- | :---- | :---- |
| List page load | Recurring Transactions list returns and renders the first page | ≤ 1.5 s (p95) for ≤ 500 templates |
| Template save | Create/update a template and recompute Next Date | ≤ 800 ms (p95) |
| Reminders List load | Query and render due reminder items | ≤ 1.5 s (p95) |
| Use / generate one bill | Materialize a bill from a template | ≤ 1 s (p95) |
| Generation job throughput | Bills produced per minute per worker | ≥ 2,000 occurrences/min |
| Job window | Full daily sweep for a large tenant completes inside its window | ≤ 10 min for 50k active templates |

## **17.2 Scalability & multi-tenancy**

* **Tenant isolation.** Every query, job selection, and API response is scoped by company\_id; no cross-tenant read or write is possible. This is enforced in the data-access layer, not only in the UI.

* **Horizontal scale.** The generation job is shardable by company\_id (or a hash range) so multiple workers run in parallel without contention.

* **Large tenants.** The design supports tenants with tens of thousands of active templates without degrading interactive list/API latency during a job sweep.

* **Indexing.** next\_run\_date, company\_id, status, and (template\_id, occurrence\_date) are indexed to keep both the interactive list and the job selection query fast (see Section 12).

## **17.3 Reliability & correctness**

* **Generation reliability ≥ 99.9%.** Of all templates due on a given day, at least 99.9% are processed on time; the remainder are caught up automatically on the next run.

* **Exactly-once posting.** The unique (template\_id, occurrence\_date) constraint guarantees a given occurrence can never post two bills, even if the job runs twice or overlaps (Section 11.6).

* **No silent data loss.** A failed occurrence is recorded with an error and retried or surfaced; it is never dropped without a trace.

* **Idempotent retries.** Re-running the job after a partial failure resumes safely and does not double-post already-created bills.

| Reliability principle It is always safer to skip and alert than to post a wrong or duplicate bill. When the engine is unsure (missing account, ambiguous state), it fails the single occurrence, leaves a clear error, and lets the rest of the run proceed. |
| :---- |

## **17.4 Security & privacy**

* **Authorization on every call.** Server-side permission checks (Section 16\) gate every template and generation action; the UI never acts as the only guard.

* **Attachment safety.** Template attachments (≤ 20 MB) are virus-scanned, access-controlled to the owning company, and served via signed, expiring URLs.

* **Data in transit & at rest.** All traffic is TLS; stored records and attachments are encrypted at rest per platform standards.

* **Auditability.** Template create/edit/delete, Use, and every automatic generation write an audit entry (actor or “system”, timestamp, before/after).

* **Least privilege for the job.** The background worker runs with a scoped service identity able to create bills and write occurrences/audit — nothing more.

## **17.5 Time zones, dates & internationalization**

* **Company-local scheduling.** All due-date math, days-in-advance, reminder offsets, and “today” comparisons use the company's configured time zone, not the server's (Section 11).

* **Date-only semantics.** Occurrence, start, and end dates are calendar dates (no time component), so a bill dated the 1st is the 1st regardless of where the worker runs.

* **Locale formatting.** Amounts and dates render in the company's locale and base-currency format; the stored values remain canonical.

* **Translatable UI.** All labels, empty states, warnings, and notification copy are externalized for localization.

## **17.6 Availability & observability**

* Interactive endpoints target the platform's standard availability SLO; a job outage delays generation but never loses it (catch-up guarantees eventual completion).

* The job emits structured metrics (processed / skipped / failed / duration) and logs per run, with alerting when the failed count or run duration crosses a threshold.

* A dead-letter path captures occurrences that fail repeatedly so on-call can inspect and remediate without blocking healthy templates.

# **18\. Notifications**

Notifications keep the user informed without pulling them into the app. The module distinguishes reminders that require a human decision from optional summaries that simply confirm automation ran. Delivery preferences are respected, and nothing here overrides a user's global notification settings.

## **18.1 Reminder notifications (Reminder-type templates)**

* **Trigger.** On a Reminder template's computed reminder date (transaction date minus the configured “remind N days before”).

* **Purpose.** Tell the responsible user that a recurring bill is coming due and needs to be created and reviewed.

* **Content.** Template name, vendor, expected amount, transaction date, and a direct link to create the bill from the reminder.

* **Grouping.** Multiple reminders due the same day may be rolled into one digest to avoid noise; each still links to its own item in the Reminders List.

* **Lifecycle.** Once the bill is created (or the occurrence is resolved), the reminder clears and no further nudges are sent for that occurrence.

## **18.2 Generation summaries (optional, Scheduled templates)**

Scheduled templates post automatically, so they need confirmation rather than a call to action. A summary is optional and off by default to avoid inbox fatigue; when enabled it reassures the user that automation is working.

* A periodic (e.g., daily or weekly) digest listing bills the engine created: vendor, amount, date, and a link to each bill.

* Immediate alerts are reserved for exceptions — e.g., an occurrence that failed because a referenced account or vendor was removed — so the user can fix the template.

## **18.3 Failure & exception alerts**

| Exceptions always surface Even with summaries disabled, a failed generation (missing account, deleted vendor, validation error) raises an alert to an authorized user with the reason and a link to the template. Silent failure is never acceptable for financial automation. |
| :---- |

## **18.4 Channels & preferences**

| Channel | Used for | Default |
| :---- | :---- | :---- |
| In-app / bell | Reminders, generation summaries, exceptions | On |
| Email | Reminders and exception alerts; optional summaries | On for reminders/exceptions |
| Digest roll-up | Multiple same-day reminders or generated-bill lists | On (grouped) |
| Autopay-related | Reserved for when autopay execution ships (Section 21\) | N/A in v1 |

* Recipients follow role and per-template responsibility; at minimum, users who can process the template receive its reminders/exceptions.

* All notification types honor the user's global preferences and unsubscribe controls; transactional exception alerts may be non-optional by policy.

# **19\. Analytics & Reporting**

Two audiences consume data from this module: end users, who need to see and manage what repeats, and the product/engineering team, who need to know whether the feature delivers value and runs reliably. Both are served without exposing one tenant's data to another.

## **19.1 User-facing report — Recurring Templates**

A dedicated report lists a company's recurring bill templates so an owner or accountant can review commitments at a glance.

* Grouped by Type (Scheduled / Reminder / Unscheduled), with per-group and overall counts.

* Columns: Template Name, Vendor, Interval, Previous Date, Next Date, Amount, and Status (active / ended).

* Shows total committed monthly/annual value where an amount and cadence are known, to support cash-flow planning.

* Filterable by vendor, type, and status; exportable (PDF/print now, CSV as a fast-follow).

| Cross-module reporting Because generated bills are ordinary bills linked to their template (source\_template\_id), existing Accounts Payable, aging, and cash-flow reports include recurring bills automatically — no separate accounting treatment is required. The template link also lets those reports attribute a bill back to its recurring source. |
| :---- |

## **19.2 Product instrumentation & success metrics**

The events below feed the success metrics defined in Section 3.4 (adoption ≥ 25%, automation rate ≥ 60%, generation reliability ≥ 99.9%, error rate \< 2%). They are aggregated for product analytics and contain no sensitive financial detail beyond what analytics requires.

| Event | Fires when | Key properties |
| :---- | :---- | :---- |
| template\_created | A template is saved | type, interval, has\_end, line\_count, days\_in\_advance / remind\_before |
| template\_edited | A template is updated | changed\_fields, type |
| template\_deleted | A template is deleted | type, age\_days, occurrences\_generated |
| bill\_generated | The job posts a Scheduled bill | template\_id, occurrence\_date, amount, latency |
| reminder\_raised | A reminder becomes due | template\_id, txn\_date |
| reminder\_actioned | A bill is created from a reminder | template\_id, time\_to\_action |
| template\_used | Use creates a bill (Unscheduled/manual) | type, edited\_before\_save |
| job\_run | A generation sweep completes | processed, skipped, failed, duration\_ms |

## **19.3 Operational dashboards**

* Reliability: on-time generation rate, job duration, failed/dead-lettered occurrences — tracked against the 99.9% bar.

* Adoption & automation: companies with ≥ 1 template, templates per company, and the share of recurring bills created by the job vs. manually.

* Health of automation: bills reversed or deleted within 48 hours of generation (the error-rate guardrail), watched for regressions after releases.

# **20\. QA & Acceptance Checklist**

This checklist turns the acceptance criteria (Section 8), business rules (Section 11), and edge cases (Section 15\) into concrete, testable items. Every box must be verifiable by QA before the module ships. It is organized by area; “✔” denotes the expected outcome.

## **20.1 List & navigation**

| \# | Test |
| ----- | :---- |
| 1 | List shows Template Name, Type, Txn Type, Interval, Previous Date, Next Date, Vendor, Amount, and Action for every template. |
| 2 | Sorting by Template Name, Next Date, Vendor, and Amount works ascending and descending. |
| 3 | “Filter by name” narrows the list case-insensitively as the user types. |
| 4 | Pagination appears past one page and preserves the active filter/sort. |
| 5 | Empty state explains recurring transactions and offers a clear call to action. |
| 6 | Amounts render in the company base currency with correct formatting. |

## **20.2 Creating templates (all three types)**

| \# | Test |
| ----- | :---- |
| 7 | “New” opens Select Transaction Type; confirming Bill opens the template form; cancelling returns to the list with nothing saved. |
| 8 | Scheduled shows “Create \_\_ days in advance”; interval, start date, and end condition are required; first Next Date is computed correctly on save. |
| 9 | Reminder shows “Remind \_\_ days before the transaction date”; no bill is ever auto-created; an item appears on the reminder date. |
| 10 | Unscheduled hides interval/start/end and never generates; it can only be used on demand. |
| 11 | Selecting a vendor auto-fills mailing address and default Terms; Terms drive the due date. |
| 12 | Category and Item lines add/remove correctly; running Total matches the sum of lines. |
| 13 | Memo and a single attachment (≤ 20 MB) save with the template; oversize files are rejected with a clear message. |
| 14 | Autopay is surfaced but gated in v1; a template can be saved and autopay enabled later without data loss. |

## **20.3 Scheduling engine & generation**

| \# | Test |
| ----- | :---- |
| 15 | Daily / weekly / monthly / yearly and “every N” intervals each produce the correct Next Date. |
| 16 | Month-end clamping: a template set to the 31st posts on the last day of shorter months (e.g., Feb 28/29). |
| 17 | “Create N days in advance” posts the bill N days before its transaction date and sets the correct bill date. |
| 18 | End conditions — None, After N occurrences, and By date — each stop generation at the right point. |
| 19 | Running the job twice for the same day never creates a duplicate (unique template\_id \+ occurrence\_date holds). |
| 20 | A delayed job catches up missed occurrences (subject to the catch-up safeguard) without duplicating. |
| 21 | An occurrence with a deleted account/vendor fails in isolation, is logged and alerted, and does not block other templates. |
| 22 | All date math uses the company time zone; a bill dated the 1st is the 1st regardless of worker location. |

## **20.4 Row actions, reminders & integrity**

| \# | Test |
| ----- | :---- |
| 23 | Use creates a bill linked to the template; it appears in payables and (for Scheduled) advances Previous/Next Date appropriately. |
| 24 | Duplicate creates an independent copy named “Copy of …” with empty run history; editing the copy never affects the original. |
| 25 | Delete confirms, stops all future generation, leaves already-generated bills untouched, and writes an audit entry. |
| 26 | Editing a template never rewrites bills already generated; only future occurrences reflect the change. |
| 27 | Changing a shared vendor/item elsewhere prompts the documented update-all vs. one-time behavior. |
| 28 | Reminders List shows due items, supports find-by-name and type filter, offers create/batch actions, and clears an item once its bill is created. |
| 29 | Permissions are enforced server-side: each role can perform only the actions in the Section 16 matrix; the UI hides/disables the rest. |
| 30 | Every template create/edit/delete, Use, and automatic generation is recorded in the audit log. |
| **Definition of done** All 30 checks pass across the three template types; performance targets in 17.1 are met at p95; and no cross-tenant access is possible in any list, API, or job path. |  |

# **21\. Future Enhancements**

The v1 scope is deliberately focused on recurring Bills, but the engine, data model, and UI are built to extend. The items below are sequenced roughly by value and effort; several were called out as non-goals in Section 3.3 and have reserved room in the schema (Section 12).

## **21.1 More recurring transaction types**

The template, schedule, and generation engine are transaction-type agnostic. Adding a new type is primarily a matter of a type-specific form and posting adapter.

* **Recurring Invoice.** Highest-value extension; reuses the Sales module's invoice form and posting, plus optional send-on-generate.

* **Recurring Expense.** For card/cash expenses that repeat; reuses the Expense module.

* **Recurring Journal Entry.** For accruals, depreciation, and allocations posted on a schedule.

* **Recurring Sales Receipt / Estimate.** Rounds out the sales side for subscription-like flows.

## **21.2 Lifecycle controls**

* **Pause / Resume.** Temporarily halt generation without deleting the template (schema reserves a paused state).

* **Skip next.** Skip a single upcoming occurrence (e.g., a one-off holiday) and continue after.

* **End early / extend.** Adjust the end condition on a running template with a clear preview of the new Next Date.

## **21.3 Payments & autopay**

* **Autopay execution.** The UI already surfaces autopay (gated in v1); a future release wires it to a payment rail so generated bills can be paid automatically with full audit and failure handling.

* **Recurring bill payments.** Optionally schedule the payment stage against generated bills, once the ambiguity around which bill a payment settles is designed away.

* **Dunning & retries.** Smart retry and escalation when an automatic payment fails.

## **21.4 Power-user & scale features**

* Bulk import/export of templates via CSV, and bulk edit across templates.

* Custom frequencies beyond the standard set (e.g., “last weekday of the month”, “every 2 weeks on Monday”).

* Approval workflow before a generated bill posts, for companies that require sign-off.

* Multi-currency-specific handling (per-template currency and FX at generation time).

* Variable amounts via formula or external feed for usage-based bills.

# **22\. Appendix**

## **22.1 Field quick-reference**

A condensed reference of the primary template fields and where each is specified in full.

| Field | Meaning | Detail in |
| :---- | :---- | :---- |
| Template name | Human label for the recurring bill | §9.3, §12 |
| Type | Scheduled / Reminder / Unscheduled behavior | §7, §9.3, §11 |
| Days in advance | How early a Scheduled bill is created | §9.3, §11.3 |
| Remind before | Lead time for a Reminder item | §9.3, §11.4 |
| Vendor / Terms | Payee and payment terms (drive due date) | §9.3, §14 |
| Interval | Frequency \+ day-of-month / weekday \+ every-N | §9.3, §11.1 |
| Start / End | When recurrence begins and stops | §9.3, §11.5 |
| Category / Item lines | Account and product/service detail \+ totals | §9.3, §12 |
| source\_template\_id | Link from a generated bill back to its template | §12, §19.1 |

## **22.2 Type-behavior summary**

| Behavior | Scheduled | Reminder | Unscheduled |
| :---- | :---- | :---- | :---- |
| Auto-creates bill | **Yes** | **No** | **No** |
| Has a timetable | Yes | Yes | — |
| Appears in Reminders List | No | Yes | No |
| Uses Next Date | Yes | Yes | — |
| Primary way to post | Automatic on due date | Create from reminder | Use from the list |

## **22.3 Change log**

| Version | Date | Change |
| :---- | :---- | :---- |
| 1.0 | Initial | First release for build: Recurring Bill with Scheduled / Reminder / Unscheduled types, scheduling engine, data model, APIs, integrations, and QA checklist. |

*End of document.*