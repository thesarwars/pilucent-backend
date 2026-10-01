**PILUCENT**  
**Accounting Platform  ·  Product & Engineering**

**Recurring Transactions**

**Expense Module**

End-to-End Product Requirements & Technical Specification

*Feature goals · User stories · Functional spec · User flows · Accounting & journal entries · Data model · APIs*

| Field | Detail |
| :---- | :---- |
| Document title | Recurring Transactions (Expense) — Product & Technical Requirements Document |
| Product area | Expenses domain · Direct spend / money-out · Recurring Transactions |
| Prepared for | Pilucent Product, Engineering & QA teams |
| Document type | Feature specification / build reference (developer-facing) |
| Version | 1.0 (Initial release for build) |
| Status | **Ready for development** |
| Prerequisite modules | Sales module, Expense (one-off) module, Vendor/Payee master, Chart of Accounts, Bank & Credit Card accounts, Products & Services, Tax engine |
| Companion module | Recurring Transactions (Bill) — shares the same scheduling engine; differs in accounting treatment |
| Related future work | Recurring Invoice, Recurring Check, Recurring Journal Entry (same engine) |

# **Table of Contents**

[**Table of Contents	2**](#heading=)

[**1\. Introduction & Purpose	3**](#heading=)

[1.1 Who this document is for	3](#heading=)

[1.2 How to read it	3](#heading=)

[**2\. Glossary & Terminology	4**](#heading=)

[**3\. Feature Goals & Objectives	5**](#heading=)

[3.1 Business goals	5](#heading=)

[3.2 User goals	5](#heading=)

[3.3 Non-goals (explicitly out of scope for v1)	5](#heading=)

[3.4 Success metrics	6](#heading=)

[**4\. Competitive Research & Market Analysis (R\&D)	7**](#heading=)

[4.1 Research method	7](#heading=)

[4.2 What the market has in common	7](#heading=)

[4.3 Where platforms differ	8](#heading=)

[**5\. Scope, Assumptions & Dependencies	9**](#heading=)

[5.1 In scope (v1)	9](#heading=)

[5.2 Out of scope (v1)	9](#heading=)

[5.3 Assumptions	9](#heading=)

[5.4 Dependencies	9](#heading=)

[**6\. User Personas	11**](#heading=)

[6.1 Priya — Owner of a small design studio	11](#heading=)

[6.2 Marcus — Bookkeeper for several clients	11](#heading=)

[6.3 Dana — Operations manager at a growing agency	11](#heading=)

[**7\. Concept Model & Feature Overview	12**](#heading=)

[7.1 Template, not a transaction	12](#heading=)

[7.2 The three types	12](#heading=)

[7.3 What makes an expense different from a bill	12](#heading=)

[7.4 Where the feature lives in Pilucent	12](#heading=)

[7.5 Template lifecycle	13](#heading=)

[**8\. User Stories & Acceptance Criteria	14**](#heading=)

[Epic A — Viewing recurring transactions	14](#heading=)

[RE-01  See all recurring templates	14](#heading=)

[RE-02  Filter and find quickly	14](#heading=)

[Epic B — Creating a recurring expense template	14](#heading=)

[RE-03  Start a new template and choose the type	14](#heading=)

[RE-04  Configure a Scheduled expense	14](#heading=)

[RE-05  Configure a Reminder expense	15](#heading=)

[RE-06  Configure an Unscheduled expense	15](#heading=)

[RE-07  Name the payee, payment account, and method	15](#heading=)

[RE-08  Build the expense body (lines, billable, memo, attachment)	15](#heading=)

[Epic C — Acting on templates	16](#heading=)

[RE-09  Use a template now	16](#heading=)

[RE-10  Duplicate a template	16](#heading=)

[RE-11  Delete a template safely	16](#heading=)

[RE-12  Edit a template without corrupting history	16](#heading=)

[Epic D — Accounting & cost recovery	17](#heading=)

[RE-13  Post correct double-entry accounting	17](#heading=)

[RE-14  Recover billable costs from customers	17](#heading=)

[**9\. Detailed Functional Specification	18**](#heading=)

[9.1 Recurring Transactions list	18](#heading=)

[9.1.1 Columns	18](#heading=)

[9.1.2 Toolbar & controls	18](#heading=)

[9.1.3 Empty & loading states	18](#heading=)

[9.2 Select Transaction Type dialog	19](#heading=)

[9.3 Recurring expense template form	19](#heading=)

[9.3.1 Identity & type	19](#heading=)

[9.3.2 Type-specific behavior	19](#heading=)

[9.3.3 Payee & payment account	20](#heading=)

[9.3.4 Schedule — interval, start & end	21](#heading=)

[9.3.5 Payment method	21](#heading=)

[9.3.6 Category details lines	21](#heading=)

[9.3.7 Item details lines	21](#heading=)

[9.3.8 Footer — total, memo, attachment, actions	22](#heading=)

[9.4 Row actions (Edit / Use / Duplicate / Delete)	22](#heading=)

[9.5 Reminders List	22](#heading=)

[9.6 “Make recurring” from an existing expense	23](#heading=)

[**10\. User Flows	24**](#heading=)

[10.1 Create a Scheduled expense (Priya — automatic)	24](#heading=)

[10.2 Reminder expense (Marcus — variable amount)	24](#heading=)

[10.3 Unscheduled \+ billable (Dana — on demand, recoverable)	24](#heading=)

[10.4 Automatic generation (the Job's path)	25](#heading=)

[10.5 Edit or delete a template	25](#heading=)

[**11\. Business Rules & Scheduling Engine	26**](#heading=)

[11.1 Frequency & next-date algorithm	26](#heading=)

[11.2 Month-end clamping	26](#heading=)

[11.3 Days-in-advance (Scheduled)	26](#heading=)

[11.4 Reminder lead time	26](#heading=)

[11.5 Start & end conditions	26](#heading=)

[11.6 The Generation Job	27](#heading=)

[11.6.1 Selection & timing	27](#heading=)

[11.6.2 Idempotency & exactly-once	27](#heading=)

[11.6.3 Catch-up after downtime	27](#heading=)

[11.6.4 Failure handling	27](#heading=)

[11.7 Editing rules (future-only)	27](#heading=)

[**12\. Accounting: Journal Entries, Posting & Ledger Impact	28**](#heading=)

[12.1 The accounting model for a direct expense	28](#heading=)

[12.2 Journal entry — simple bank expense	28](#heading=)

[12.3 Journal entry — credit-card expense	28](#heading=)

[12.4 Journal entry — split (multi-line) expense	29](#heading=)

[12.5 Journal entry — expense with purchase tax	29](#heading=)

[12.6 Billable / reimbursable expenses	29](#heading=)

[Stage 1 — when the expense posts	29](#heading=)

[Stage 2 — when the customer is invoiced	30](#heading=)

[12.7 Ledger & register impact	30](#heading=)

[12.8 How recurring generation posts	31](#heading=)

[12.9 Reconciliation & audit	31](#heading=)

[12.10 Reversals & deletions	31](#heading=)

[**13\. Data Model	32**](#heading=)

[13.1 recurring\_template	32](#heading=)

[13.2 recurring\_schedule (fields / value object)	33](#heading=)

[13.3 recurring\_template\_line	33](#heading=)

[13.4 recurring\_occurrence	34](#heading=)

[13.5 New columns on the expense record	34](#heading=)

[13.6 Sample template (JSON)	34](#heading=)

[**14\. API Specification	36**](#heading=)

[14.1 Endpoint summary	36](#heading=)

[14.2 List templates	36](#heading=)

[14.3 Create template	37](#heading=)

[14.4 Use a template now	37](#heading=)

[14.5 List & resolve reminders	37](#heading=)

[14.6 Error model	37](#heading=)

[**15\. Integration with Other Modules	39**](#heading=)

[**16\. Edge Cases, Validation & Error Handling	40**](#heading=)

[16.1 Validation rules (form & API)	40](#heading=)

[16.2 Behavioral edge cases	40](#heading=)

[16.3 Error-handling principles	41](#heading=)

[**17\. Permissions & Roles	42**](#heading=)

[**18\. Non-Functional Requirements	43**](#heading=)

[18.1 Performance	43](#heading=)

[18.2 Scalability & multi-tenancy	43](#heading=)

[18.3 Reliability & correctness	43](#heading=)

[18.4 Security & privacy	43](#heading=)

[18.5 Time zones, dates & i18n	44](#heading=)

[18.6 Availability & observability	44](#heading=)

[**19\. Notifications	45**](#heading=)

[19.1 Reminder notifications (Reminder templates)	45](#heading=)

[19.2 Generation summaries (optional, Scheduled templates)	45](#heading=)

[19.3 Failure & exception alerts	45](#heading=)

[19.4 Channels & preferences	45](#heading=)

[**20\. Analytics & Reporting	47**](#heading=)

[20.1 User-facing report — Recurring Templates	47](#heading=)

[20.2 Product instrumentation & success metrics	47](#heading=)

[20.3 Operational dashboards	48](#heading=)

[**21\. QA & Acceptance Checklist	49**](#heading=)

[21.1 List, create & schedule	49](#heading=)

[21.2 Payment, lines & billable	49](#heading=)

[21.3 Accounting & ledger (Section 12\)	49](#heading=)

[21.4 Generation, actions & integrity	50](#heading=)

[**22\. Future Enhancements	53**](#heading=)

[22.1 More recurring transaction types	53](#heading=)

[22.2 Lifecycle controls	53](#heading=)

[22.3 Banking, recovery & scale	53](#heading=)

[**23\. Appendix	54**](#heading=)

[23.1 Field quick-reference	54](#heading=)

[23.2 Type-behavior summary	54](#heading=)

[23.3 Expense vs. Bill — accounting cheat-sheet	54](#heading=)

[23.4 Change log	55](#heading=)

*Tip: right-click the table above in Word and choose “Update Field” to refresh page numbers.*

# **1\. Introduction & Purpose**

This document is the complete build reference for the Recurring Expense feature in Pilucent. It specifies, in one place, everything a product manager, engineer, or QA analyst needs to design, build, and verify the feature: why it exists, how it behaves on every screen, the rules that govern scheduling, the exact accounting it posts, the data it stores, the APIs it exposes, and how it connects to the rest of the platform.

A recurring expense is a saved template for a purchase the business pays for repeatedly and immediately — a monthly software subscription paid by card, weekly fuel paid from checking, a rent payment drawn straight from the bank. Instead of re-entering the same expense every period, the user sets it up once and Pilucent either posts it automatically or reminds them to.

| The one distinction that shapes this entire module An Expense is money already paid. Unlike a Bill — which records money owed and sits in Accounts Payable until settled — an Expense posts immediately against a payment account (a bank or credit card). It never touches Accounts Payable, has no due date, and hits the profit & loss the moment it is created. Every rule, field, and journal entry in this document follows from that fact. |
| :---- |

Pilucent already ships a Sales module and an Expense module for one-off spend. This feature adds the recurring layer on top of the existing Expense transaction, reusing its form, its posting logic, and its place in the ledger. It is a sibling to the Recurring Bill module and shares the same scheduling engine; the two differ only in what they post and when money moves.

## **1.1 Who this document is for**

* **Engineers** — for data model, APIs, scheduling logic, accounting posting, and integration points.

* **Product & design** — for goals, user stories, flows, and screen behavior.

* **QA** — for acceptance criteria, edge cases, and the end-to-end test checklist.

* **Accounting reviewers** — for the journal entries, ledger impact, and reconciliation behavior in Section 12\.

## **1.2 How to read it**

Sections 1–8 give the product context (goals, personas, stories). Sections 9–11 specify behavior (screens, flows, scheduling). Section 12 is the accounting contract — journal entries, posting, and ledger impact. Sections 13–15 are the technical build (data, APIs, integrations). Sections 16–23 cover quality, permissions, and operations. Each section stands alone but cross-references the others.

# **2\. Glossary & Terminology**

Consistent language keeps the spec unambiguous. These terms are used precisely throughout the document.

| Term | Meaning in this document |
| :---- | :---- |
| Recurring expense template | The saved definition of a repeating expense: payee, payment account, amount lines, schedule, and type. The template is not itself an expense; it produces them. |
| Generated expense | An actual expense transaction the system creates from a template on a given date. It posts to the ledger like any manually entered expense. |
| Type | One of Scheduled, Reminder, or Unscheduled — controls whether the system posts automatically, only nudges, or waits to be used on demand. |
| Payee | Who was paid — a vendor, contractor, or supplier. Answers “Who did you pay?” Backed by the Vendor/Payee master. |
| Payment account | The bank or credit card the money comes from. This is the account credited in the journal entry — the defining field of an expense. |
| Payment method | How the payment was made (cash, check, credit card, EFT). Descriptive metadata; does not change the accounting on its own. |
| Category line | A line that charges an amount to an account (e.g., Rent, Utilities). Drives the debit side of the journal entry. |
| Item line | A line for a product/service with quantity and rate, mapped to an account. Also drives the debit side. |
| Billable | A flag marking a line as recoverable from a customer. The amount is tracked so it can later be added to that customer's invoice. |
| Interval / schedule | The frequency rule (daily / weekly / monthly / yearly, every N, on a day-of-month or weekday) that decides the next date. |
| Generation Job | The scheduled background process that posts Scheduled expenses and raises reminders when they are due. |
| Posting | Writing the double-entry journal (debits and credits) to the general ledger so the transaction affects reports and account balances. |
| Register / ledger | The running list of transactions in an account (e.g., the checking register). A generated expense appears here immediately. |

# **3\. Feature Goals & Objectives**

The feature removes repetitive data entry for money that goes out on a regular cadence, while keeping the user in control and the books correct. Because an expense moves real money the instant it posts, accuracy and predictability matter even more here than for a bill.

## **3.1 Business goals**

* **Eliminate repeat entry for regular spend.** Set up a subscription, rent, or retainer once; never re-type it.

* **Keep the cash and card position current.** Because recurring spend posts on schedule, the bank and credit-card balances and the P\&L reflect it without manual effort.

* **Reduce errors and missed entries.** A template posts the same accounts, amounts, and tax every period, so nothing is forgotten or miscoded.

* **Improve reimbursable-cost recovery.** Billable lines are captured automatically each period, so client-recoverable costs are not left un-invoiced.

* **Reach feature parity.** Recurring expenses are expected in cloud accounting; their absence is a common reason prospects reject a product during evaluation.

## **3.2 User goals**

* Automate fixed, unchanging payments (e.g., a card subscription) so they post without any effort.

* Get a timely nudge for spend that recurs but whose amount varies, then review before posting.

* Keep a library of complex expenses that are re-used irregularly, so they never have to be rebuilt.

* Always know what has left the bank/card and what is coming, and see it reflected in reports.

* Recover billable costs from customers without tracking them by hand.

* Edit, duplicate, or stop a recurring expense safely, without disturbing expenses already posted or reconciled.

## **3.3 Non-goals (explicitly out of scope for v1)**

Stating what we are not building keeps the release focused and shippable. Several of these appear again in Section 22 as future work.

* Recurring bills, invoices, sales receipts, checks, or journal entries (the engine will support them later; only Expense ships now).

* Automatic bank-feed matching of generated expenses to real card/bank charges (surfaced as a reconciliation consideration in Section 12, automated later).

* Multi-currency-specific FX handling per template (single base-currency behavior in v1).

* Pause / Resume / Skip-next controls (planned as a fast-follow; the data model reserves room for them).

* Bulk import/export of templates via CSV (planned as a fast-follow).

## **3.4 Success metrics**

| Metric | Definition | Target (first 90 days) |
| :---- | :---- | :---- |
| Adoption | % of active companies with ≥1 recurring expense template | ≥ 25% |
| Template volume | Median templates per adopting company | ≥ 3 |
| Automation rate | % of recurring expenses created by the job vs. manually | ≥ 60% |
| Billable capture | % of billable recurring lines invoiced to a customer within 30 days | ≥ 70% |
| Generation reliability | % of due templates posted on time by the job | ≥ 99.9% |
| Error rate | % of generated expenses reversed/deleted within 48h | \< 2% |

# **4\. Competitive Research & Market Analysis (R\&D)**

Before designing the feature, we studied how recurring, immediately-paid spend is handled across the leading cloud accounting platforms used by small and mid-sized businesses. The goal was to identify the mental model users already expect, the fields that genuinely matter for a paid-now transaction, and the accounting treatment mature products converge on. To keep this document vendor-neutral, competitors are referenced as Platform A, Platform B, and Platform C rather than by brand name.

## **4.1 Research method**

* Reviewed public help documentation, setup guides, and API references for three leading platforms covering recurring expenses specifically (as distinct from recurring bills).

* Mapped every user-facing field on the recurring-expense form, the available frequency options, and the actions offered on a saved template.

* Traced the accounting each platform posts for a paid expense — which account is debited, which is credited, and how billable and tax lines are handled.

* Catalogued behavioral edge cases (month-end dates, editing a live template, deleting one, time-zone of generation) and how billable costs flow to customer invoices.

## **4.2 What the market has in common**

Despite different naming, the platforms converge on the same core ideas. This convergence is the strongest signal for what Pilucent should adopt.

* **Expense is separate from Bill.** Every platform treats a recurring expense as a paid transaction that posts directly, and a recurring bill as an unpaid obligation that sits in Accounts Payable until settled. The two are distinct features with distinct accounting.

* **Template-driven, parent–child.** A reusable template (or “profile”) produces many dated expenses; editing the template affects future children only, never those already posted.

* **A behavior spectrum.** From fully automatic, to a reminder that requires review, to a purely manual on-demand template — the same three types Pilucent will adopt.

* **A payment account is mandatory.** Because the money is already gone, every expense names the bank or card it came from; that account is the credit side of the entry.

* **No terms, no due date.** Unlike bills, expenses carry no payment terms or due date — there is nothing left to pay.

* **A frequency engine.** Daily / weekly / monthly / yearly plus an “every N periods” multiplier and a day-of-month or weekday selector, with month-end handling.

* **Billable-to-customer.** A line can be flagged billable and tied to a customer, so a recurring cost can later be recovered on that customer's invoice.

* **Make-recurring & lifecycle.** An existing one-off expense can be turned into a template, and a template can be stopped so it no longer generates while posted expenses remain untouched.

## **4.3 Where platforms differ**

| Dimension | Observed variation across platforms |
| :---- | :---- |
| Behavior model | Platform A offers three explicit types (auto / reminder / on-demand). Platforms B and C lean on “auto-post vs. profile” toggles rather than a named spectrum. Pilucent adopts the clearer three-type model. |
| Item vs. category lines | Some expose only a category (account) grid; others also expose an item (product/service) grid on purchase forms, sometimes behind a setting. Pilucent includes both, matching its existing Expense screen. |
| Billable treatment | Platforms differ on whether a billable expense posts to the expense account and is flagged, or to a current-asset holding account. Pilucent posts to the expense account and tracks the billable amount (see Section 12.6). |
| Tax on purchases | Handling of input/purchase tax varies by region and configuration — embedded in the amount, or split to a tax-on-purchases account. Pilucent defers to the existing Tax engine and the company's setup. |
| Generation timing | Generation runs on a platform schedule in the organization's time zone (commonly early morning). Pilucent runs at least daily in the company's configured time zone. |
| Stop vs. delete | Some offer Stop/Resume plus delete; others only delete. In all cases, deleting or stopping affects future generation only. Pilucent ships delete in v1 and reserves Stop/Resume for a fast-follow. |
| **R\&D conclusion** Adopt the market-standard model: a template-driven, parent–child recurring expense with the three-type spectrum, a mandatory payment account, no terms/due date, the shared frequency engine, billable-to-customer support, and direct posting to the ledger — delivered through Pilucent's existing Expense form and accounting so it feels native, not bolted on. |  |

# **5\. Scope, Assumptions & Dependencies**

## **5.1 In scope (v1)**

* A central Recurring Transactions list page that displays all recurring templates for the company (hosting expenses in this release).

* A “New” flow that asks which transaction type to create (Expense in v1) before opening the template form.

* A recurring expense template form supporting all three types, with payee, payment account, payment method, interval, start/end, category and item lines, memo, and one attachment.

* A background Generation Job that posts Scheduled expenses and raises reminders when due.

* A Reminders List page showing reminder-type items that are due for action.

* Row actions: Edit, Use, Duplicate, Delete.

* Correct double-entry accounting for every generated expense, including split lines, tax, and billable-to-customer tracking (Section 12).

* Full integration with the existing Payee/Vendor, Bank & Credit Card accounts, Chart of Accounts, Products & Services, Tax, and Customer records.

* Audit logging of template create/edit/delete and every generation event.

## **5.2 Out of scope (v1)**

* All non-Expense transaction types (bill, invoice, check, journal entry).

* Automatic bank-feed matching of generated expenses to real charges.

* Pause/Resume/Skip, CSV import/export, and multi-currency-specific FX per template.

## **5.3 Assumptions**

* The one-off Expense screen, Payee/Vendor master, bank & credit-card accounts, Chart of Accounts, Products & Services, Tax engine, and Customer records already exist and are the source of truth.

* Each company (tenant) has a configured time zone; all scheduling and “today” comparisons use it.

* A reliable background job runner (cron/queue/worker) is available to run generation at least daily.

* Users are already authenticated and scoped to a company; standard role-based permissions apply.

## **5.4 Dependencies**

| Depends on | Why |
| :---- | :---- |
| Chart of Accounts | Category lines post to expense/asset accounts; the payment account is a bank or credit-card account. |
| Bank & Credit Card accounts | The payment account is credited on every expense and its register/balance updates immediately. |
| Payee / Vendor master | Answers “Who did you pay?” and supplies defaults on the template. |
| Products & Services | Item lines reference a product/service that maps to an account and tax. |
| Tax engine | Computes purchase/input tax on lines per the company's configuration. |
| Customer records | Billable lines tie a recoverable cost to a customer for later invoicing. |
| General Ledger / posting service | Writes the double-entry journal for each generated expense (Section 12). |
| Background job runner | Executes the Generation Job on schedule. |
| Notification service | Delivers reminders and exception alerts (Section 19). |

# **6\. User Personas**

Three personas represent the distinct ways people use recurring expenses. Each maps naturally to one of the three template types, and each appears again in the user stories and flows.

## **6.1 Priya — Owner of a small design studio**

* **Context:** Runs the business herself; pays a fixed monthly software subscription on the company card.

* **Needs:** It to post itself every month with zero effort and show up on the card balance and P\&L automatically.

* **Maps to:** Scheduled — fixed amount, fully automatic.

## **6.2 Marcus — Bookkeeper for several clients**

* **Context:** Handles a recurring utility paid by bank transfer whose amount changes each month.

* **Needs:** A reminder a few days before it is due so he can enter the real amount before it posts.

* **Maps to:** Reminder — recurring cadence, human enters the final figure.

## **6.3 Dana — Operations manager at a growing agency**

* **Context:** Occasionally pays a contractor whose cost is rebilled to a specific client; the timing is irregular.

* **Needs:** A ready-made template she can post on demand, with the billable line already tied to the client.

* **Maps to:** Unscheduled — no timetable, used when the payment actually happens.

# **7\. Concept Model & Feature Overview**

This section gives the shared mental model before the detailed spec. Everything else in the document builds on these ideas.

## **7.1 Template, not a transaction**

A recurring expense template is a definition, not an expense. It stores the payee, payment account, amount lines, and schedule. Expenses are produced from it — automatically for Scheduled templates, or on demand for the others. Editing the template changes future expenses only; expenses already posted are never rewritten.

## **7.2 The three types**

| Type | What the system does | Best for |
| :---- | :---- | :---- |
| **Scheduled** | Posts the expense automatically on each due date, optionally a few days in advance. | Fixed, unchanging spend — subscriptions, rent by auto-draft. |
| **Reminder** | Creates nothing automatically; on the reminder date it places an item in the Reminders List for a human to review and post. | Recurring spend whose amount varies — utilities, usage-based fees. |
| **Unscheduled** | Keeps the template on the shelf until used; no timetable, no reminders. | Irregular but repeatable payments — ad-hoc contractor costs. |

A user can change a template's type at any time. Switching to Scheduled or Reminder reveals the interval and start/end fields; switching to Unscheduled hides them because an unscheduled template has no timetable.

## **7.3 What makes an expense different from a bill**

Because Pilucent also offers recurring bills, it is worth stating the difference plainly — it drives the fields and the accounting.

| Aspect | Recurring Expense (this doc) | Recurring Bill (companion) |
| :---- | :---- | :---- |
| Money | **Already paid** | Owed, paid later |
| Posts to | Payment account (bank/card) | Accounts Payable |
| Due date / terms | None | Yes (terms drive due date) |
| Second step to settle | None — done at posting | A separate bill payment |
| P\&L / cash impact | Immediate | Expense now, cash on payment |
| Key extra field | Payment account \+ method | Vendor terms |

## **7.4 Where the feature lives in Pilucent**

Recurring Transactions is a shared list that can host multiple transaction types, but in v1 it hosts expenses. Conceptually it sits in the Expenses domain alongside the existing Expense and Bill screens. The entry points are:

* **Recurring Transactions list** — the home base for every template.

* **“Make recurring” on an existing expense** — a shortcut that turns an expense the user is already editing into a template (see Section 9.6).

* **Reminders List** — a focused view of reminder-type items that are due for action.

## **7.5 Template lifecycle**

| Stage | What happens |
| :---- | :---- |
| Created | The user saves a template. If it is Scheduled or Reminder, the engine computes its first Next Date from the start date and interval. |
| Active | The template is live. On each due date the Generation Job either posts an expense (Scheduled) or raises a reminder (Reminder). Previous Date and Next Date advance after each run. Unscheduled templates are “active” only in that they can be used at any time. |
| Ended | The schedule reaches its end condition (last occurrence reached, or end date passed). No further expenses or reminders are produced. The template remains visible for reference and can be reactivated by editing its end condition. |
| Deleted | The user deletes the template. Future generation stops immediately. All expenses already posted remain in the ledger and on any completed reconciliations, untouched. The template is soft-deleted so history and audit links survive. |

# **8\. User Stories & Acceptance Criteria**

Requirements are expressed as user stories grouped into epics. Each uses the standard “As a … I want … so that …” form and is followed by testable acceptance criteria (AC). QA should be able to write test cases directly from the AC. Story IDs (RE-xx) are stable references used elsewhere in the document.

## **Epic A — Viewing recurring transactions**

### **RE-01  See all recurring templates**

As a *user managing my books*, I want a single list of every recurring expense template so that I can see everything that repeats in one place.

#### **Acceptance criteria**

* The list shows columns: Template Name, Type, Txn Type, Interval, Previous Date, Next Date, Payee, Amount, and an Action menu.

* Templates are sortable by Template Name, Next Date, Payee, and Amount.

* A “Filter by name” box narrows the list as the user types.

* When there are no templates, an empty state explains what recurring transactions are and offers a “New” action.

* Amounts display in the company's base currency with correct formatting.

### **RE-02  Filter and find quickly**

As a *bookkeeper with many templates*, I want to filter the list so that I can find a specific template fast.

#### **Acceptance criteria**

* Name filter matches on partial, case-insensitive text.

* A type/txn filter lets the user narrow to a transaction type (Expense) or template type.

* Pagination appears when the list exceeds one page; the current range (e.g., “1–2”) is shown.

## **Epic B — Creating a recurring expense template**

### **RE-03  Start a new template and choose the type**

As a *user*, I want to create a new recurring transaction and pick which type of transaction it is, so that I can build the right kind of template.

#### **Acceptance criteria**

* Selecting “New” opens a “Select Transaction Type” dialog with a dropdown.

* In v1 the dropdown contains Expense (the architecture allows more types later).

* Confirming opens the recurring expense template form; cancelling returns to the list with no changes.

### **RE-04  Configure a Scheduled expense**

As *Priya (owner)*, I want an expense to post automatically so that fixed spend like a card subscription is entered without me.

#### **Acceptance criteria**

* Choosing Type \= Scheduled reveals a “Create \_\_ days in advance” field.

* Interval, Start date, and End condition fields are shown and required.

* On save, the engine computes the first Next Date and the template becomes active.

* On each due date the expense is posted automatically, linked to the template, and reflected on the payment account (Section 12).

### **RE-05  Configure a Reminder expense**

As *Marcus (bookkeeper)*, I want to be reminded before a variable expense is due so that I can enter the correct amount and post it myself.

#### **Acceptance criteria**

* Choosing Type \= Reminder reveals a “Remind \_\_ days before the transaction date” field.

* No expense is ever posted automatically for a Reminder template.

* On the reminder date, an item appears in the Reminders List and a notification is sent.

* From the reminder, the user can open, adjust the amount, and post the expense in one flow.

### **RE-06  Configure an Unscheduled expense**

As *Dana (ops manager)*, I want to save a complex expense without a schedule so that I can reuse it whenever it is actually needed.

#### **Acceptance criteria**

* Choosing Type \= Unscheduled hides the interval and start/end fields and shows an explanatory note.

* The template saves with no Next Date and never posts an expense on its own.

* The template can be turned into an expense anytime via the Use action.

### **RE-07  Name the payee, payment account, and method**

As a *user*, I want to record who I paid, which account the money came from, and how I paid, so that the expense posts to the right bank or card.

#### **Acceptance criteria**

* Payee (“Who did you pay?”) selects from the Vendor/Payee master and may auto-fill defaults.

* Payment account is required and lists the company's bank and credit-card accounts; it is the account credited when the expense posts.

* Payment method (cash, check, credit card, EFT) is optional metadata and does not by itself change the accounting.

* No payment terms or due-date field is shown — an expense is already paid.

### **RE-08  Build the expense body (lines, billable, memo, attachment)**

As a *user*, I want the template to capture the same detail as a normal expense so that generated expenses are complete, correct, and recoverable where needed.

#### **Acceptance criteria**

* Category details lines support Category (account), Description, Amount, Billable, Tax, and Customer.

* Item details lines support Product/Service, Description, Qty, Rate, Amount, Billable, Tax, and Customer.

* Add/remove line rows; a running Total is displayed and matches the sum of all lines and tax.

* A line marked Billable requires a Customer and is tracked for later invoicing (Section 12.6).

* Memo and a single Attachment (≤ 20 MB) can be added to the template.

## **Epic C — Acting on templates**

### **RE-09  Use a template now**

As *Dana*, I want to create an expense from a template on demand so that I can record an irregular payment without rebuilding it.

#### **Acceptance criteria**

* Use opens a pre-filled expense (editable) or posts it directly, depending on the type.

* For Unscheduled and Reminder templates, Use is the primary way an expense is produced.

* The created expense is linked to the template, posts to the payment account, and appears in that account's register.

### **RE-10  Duplicate a template**

As a *user*, I want to duplicate a template so that I can build a similar one without starting over.

#### **Acceptance criteria**

* Duplicate creates a copy pre-filled with all fields, named “Copy of …”.

* The copy is independent; editing it does not affect the original.

* The copy starts with no run history (empty Previous Date).

### **RE-11  Delete a template safely**

As a *user*, I want to delete a template so that it stops generating — without disturbing expenses already posted.

#### **Acceptance criteria**

* Delete asks for confirmation and warns that future generation will stop.

* After delete, no further expenses/reminders are produced.

* Expenses already posted remain in the ledger and on any completed reconciliations, unchanged.

* The action is recorded in the audit log.

### **RE-12  Edit a template without corrupting history**

As a *user*, I want edits to apply going forward so that past, posted expenses are never silently changed.

#### **Acceptance criteria**

* Edit opens the template pre-filled with its current values.

* Saving recalculates Next Date if the interval or start date changed.

* Changes never alter expenses already posted.

* If a referenced item, payee, or account was changed elsewhere, the user is warned before saving.

## **Epic D — Accounting & cost recovery**

### **RE-13  Post correct double-entry accounting**

As *an accountant*, I want every generated expense to post the correct debits and credits so that the books and account balances are always right.

#### **Acceptance criteria**

* Each category/item line debits its account; any tax posts per the Tax engine; the payment account is credited for the total (Section 12).

* A bank payment account decreases in balance; a credit-card payment account increases in liability.

* The generated expense appears immediately in the payment account's register and on the P\&L.

* The entry balances (total debits \= total credits) and is stamped with the occurrence date.

### **RE-14  Recover billable costs from customers**

As *Dana*, I want billable recurring costs tracked against a customer so that I can add them to that customer's invoice later.

#### **Acceptance criteria**

* A billable line records the amount, the customer, and its billable status when the expense posts.

* The billable amount is available to add to a matching customer invoice in the Sales module.

* Once invoiced, the line is marked billed so it is not double-recovered.

# **9\. Detailed Functional Specification**

This section specifies every screen in the feature: its layout, each field, the rules that govern it, and the states it can be in. Field tables use a consistent shape — Field, Control, Required, and Behavior/Rules — so engineers and QA can work directly from them. Screens are described in the order a user encounters them.

## **9.1 Recurring Transactions list**

The list is the home of the feature. It shows all recurring templates for the company and is where users go to review, create, and act on them. The screen has a header (title, feedback link, a view switcher, and a New button), a toolbar (name filter and a Filter control), and the templates table.

### **9.1.1 Columns**

| Column | Source | Behavior |
| :---- | :---- | :---- |
| Template Name | template.name | Clickable; opens the template for editing. Sortable. Primary identifier. |
| Type | template.type | Scheduled / Reminder / Unscheduled. |
| Txn Type | template.txn\_type | Expense in v1. Reserved for future types. |
| Interval | derived from schedule | Human-readable summary, e.g., “Every Month on the 1st”. Blank for Unscheduled. |
| Previous Date | template.previous\_run\_date | Date of the last posted expense/reminder; blank until first run. |
| Next Date | template.next\_run\_date | Next due date; blank for Unscheduled and Ended templates. |
| Payee | payee.display\_name | Who was paid. Clickable to the payee record. Sortable. |
| Amount | template total | Sum of all lines \+ tax, in base currency. Right-aligned. Sortable. |
| Action | — | Row menu: Edit (default) plus Use, Duplicate, Delete. |

### **9.1.2 Toolbar & controls**

* **Filter by Name** — live, case-insensitive, partial-match text filter.

* **Filter** — opens filter options (transaction type, template type); the current filter label (e.g., “All”) is shown beside it.

* **New** — opens the Select Transaction Type dialog (Section 9.2).

* **View switcher** — toggles between the Recurring Transactions view and the Reminders List view.

* **Print / Settings (gear)** — print the list and choose which columns are visible.

### **9.1.3 Empty & loading states**

* Empty: a short explanation of recurring transactions and a primary “New” button.

* Loading: a skeleton of the table; the first page returns within the performance budget (Section 18).

## **9.2 Select Transaction Type dialog**

Choosing New opens a small dialog that asks which kind of recurring transaction to create. This keeps the list generic while sending the user to the correct form.

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Transaction Type | Dropdown | Lists available types; v1 \= Expense. Selecting Expense and confirming opens the recurring expense template form. |
| Confirm | Button | Proceeds to the template form for the chosen type. |
| Cancel | Button | Closes the dialog; returns to the list unchanged. |

## **9.3 Recurring expense template form**

This is the core screen. It mirrors the one-off Expense form so generated expenses are identical to hand-entered ones, with a recurring header on top. The form is grouped into: identity & type, payee & payment, schedule, payment method, line details, and footer (memo, attachment, total, actions).

### **9.3.1 Identity & type**

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Template name | Text | Required. Human label shown in the list. Must be unique within the company (case-insensitive) to avoid confusion. |
| Type | Dropdown | Required. Scheduled / Reminder / Unscheduled. Changing it shows/hides schedule fields (9.3.2). |

### **9.3.2 Type-specific behavior**

| Type | What the form shows and does |
| :---- | :---- |
| Scheduled | Shows “Create \_\_ days in advance”. Interval, Start date, and End are required. On each due date the expense is posted automatically and linked to the template. |
| Reminder | Shows “Remind \_\_ days before the transaction date”. Interval, Start date, and End are required. Nothing posts automatically; a reminder item is raised on the reminder date. |
| Unscheduled | Hides interval and start/end and shows a short note that the template has no timetable and is used on demand. |
| **Days in advance** “Create N days in advance” lets a Scheduled expense post a few days before its transaction date (e.g., to record a card charge that clears early). N \= 0 means post on the date itself. The transaction (occurrence) date is what drives the accounting period, regardless of how many days early it is created. |  |

### **9.3.3 Payee & payment account**

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Payee (“Who did you pay?”) | Searchable dropdown | Optional but recommended. Selects a vendor/contractor from the Payee master; may auto-fill defaults. New payees can be added inline. |
| Payment account | Dropdown | Required. Lists bank and credit-card accounts. This is the account credited on every generated expense (Section 12\) — the defining field of an expense. |
| **Why payment account is mandatory** **An expense is money that has already left an account.** The payment account is therefore required and forms the credit side of the journal entry. A bank account decreases when the expense posts; a credit-card account increases as a liability. Because of this, there is no “terms” or “due date” field — nothing remains to be paid. |  |  |

### **9.3.4 Schedule — interval, start & end**

The interval builder answers “how often” and “starting when”. It is shown for Scheduled and Reminder templates and hidden for Unscheduled.

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Interval (frequency) | Dropdown | Daily / Weekly / Monthly / Yearly. Drives which sub-selectors appear. |
| On day / weekday | Dropdown(s) | For Monthly: “on day” \+ a day-of-month (1st–31st, clamped to month end). For Weekly: weekday(s). For Yearly: month \+ day. |
| Every N | Number | The “of every N month(s)/week(s)…” multiplier (≥ 1\) for cadences like every 2 weeks or every 3 months. |
| Start date | Date picker | Required for scheduled/reminder. The first date considered. Expenses are not generated for dates before today at creation time. |
| End | Dropdown | None (runs forever) / By date / After N occurrences. Reveals a date or count field as needed. |

*Example from a typical setup: Interval \= Monthly, on day \= 1st, of every 1 month, Start \= the 1st of next month, End \= None — an expense that posts on the 1st of every month indefinitely.*

### **9.3.5 Payment method**

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Payment Method | Dropdown | Optional. Cash / Check / Credit Card / EFT, etc. Descriptive metadata carried onto the generated expense; it does not by itself change the posting (the payment account does). May pre-set based on the chosen payment account. |

### **9.3.6 Category details lines**

Category lines charge amounts to accounts (the debit side). Each generated expense copies these lines.

| Column | Behavior / Rules |
| :---- | :---- |
| \# | Row number; rows can be reordered, duplicated, or deleted. |
| Category | The account charged (e.g., Rent, Software). Required on a used line. Drives the debit. |
| Description | Free text carried to the posted expense. |
| Amount | Line amount in base currency. Contributes to the Total. |
| Billable | Checkbox; if set, the line is recoverable and requires a Customer (Section 12.6). |
| Tax | Tax code/rate applied per the Tax engine; may add a tax line to the entry. |
| Customer | The customer a billable line is recovered from; required when Billable is checked. |

* Add lines / Clear all lines controls manage the grid; each row has duplicate and delete icons.

### **9.3.7 Item details lines**

Item lines record products/services with quantity and rate; each maps to an account and tax. They are optional and used when the purchase is tracked by item.

| Column | Behavior / Rules |
| :---- | :---- |
| \# | Row number; reorder / duplicate / delete. |
| Product/Service | References Products & Services; maps to an account and default tax. |
| Description | Defaults from the item; editable. |
| Qty / Rate | Quantity × Rate computes the line Amount. |
| Amount | Computed; contributes to the Total. |
| Billable / Tax / Customer | Same behavior as category lines (billable requires a customer). |

### **9.3.8 Footer — total, memo, attachment, actions**

| Element | Behavior / Rules |
| :---- | :---- |
| Total | Read-only running sum of all category \+ item lines and tax, in base currency. Shown as the template's Amount in the list. |
| Memo | Free-text note copied to every generated expense. |
| Attachments | A single file up to 20 MB may be attached to the template (e.g., a contract). Oversize files are rejected with a clear message. |
| Save template | Validates the form, computes the first Next Date (scheduled/reminder), and saves the template as active. |
| Cancel | Discards changes and returns to the list; a confirmation appears if there are unsaved edits. |

## **9.4 Row actions (Edit / Use / Duplicate / Delete)**

| Action | Behavior |
| :---- | :---- |
| Edit | Default row click. Opens the template pre-filled; saving applies to future expenses only (RE-12). |
| Use | Produces an expense now — pre-filled and editable, or posted directly — depending on type. Links it to the template and posts to the payment account. |
| Duplicate | Creates an independent “Copy of …” template with empty run history. |
| Delete | Confirms, stops future generation, leaves posted expenses untouched, and writes an audit entry. |

## **9.5 Reminders List**

A focused view of reminder-type items that are due. Reached from the view switcher. It exists so variable expenses are reviewed and posted deliberately.

| Element | Behavior |
| :---- | :---- |
| Due items | Shows reminder items due now, with Template name, Payee, expected Amount, and transaction date. |
| Find & filter | Supports find-by-name and a transaction-type filter. |
| Create action | Each item offers “create the expense”; the user can adjust the amount before posting. Batch actions may be offered. |
| Empty state | When nothing is due, a clear empty state is shown. |
| Resolution | Once the expense is posted, the reminder item is cleared and won't nudge again for that occurrence. |

## **9.6 “Make recurring” from an existing expense**

A shortcut lets a user turn an expense they already created into a recurring template, so they don't rebuild it.

* From an existing expense, “Make recurring” opens the template form pre-filled from that expense (payee, payment account, lines, memo).

* The user adds a template name, type, and — for scheduled/reminder — an interval and start/end, then saves.

* The original expense is unchanged; the new template governs future occurrences only.

# **10\. User Flows**

These flows trace the main journeys end to end, step by step. They complement the screen spec (Section 9\) and the scheduling rules (Section 11), and each ends in a clear accounting outcome (Section 12).

## **10.1 Create a Scheduled expense (Priya — automatic)**

1. From the Recurring Transactions list, Priya clicks New and selects Expense.

2. She names the template “Design Software — Monthly” and sets Type \= Scheduled, Create 0 days in advance.

3. She picks Payee \= “Pixelworks” and Payment account \= “Business Credit Card”, method \= Credit Card.

4. She sets Interval \= Monthly on the 1st of every 1 month, Start \= the 1st of next month, End \= None.

5. She adds one category line: Software Subscriptions, $49.00, not billable.

6. She clicks Save template. Pilucent computes Next Date \= the 1st of next month and marks the template active.

7. On that date the Generation Job posts a $49 expense against the credit card, links it to the template, and advances Previous/Next Date. The card liability rises by $49 and the P\&L shows the subscription (Section 12.2).

## **10.2 Reminder expense (Marcus — variable amount)**

1. Marcus creates a template “Electricity” with Type \= Reminder, Remind 3 days before the transaction date.

2. Payee \= “City Power”, Payment account \= “Checking”; Interval \= Monthly on the 5th; Start set; End \= None.

3. He adds a category line Utilities with a placeholder amount and saves. Nothing posts yet.

4. Three days before the 5th, an item appears in the Reminders List and Marcus is notified.

5. He opens it, enters the actual amount from the bill, and posts the expense. Checking decreases and Utilities hits the P\&L.

6. The reminder clears; next month the cycle repeats.

## **10.3 Unscheduled \+ billable (Dana — on demand, recoverable)**

1. Dana saves an Unscheduled template “Contractor — Acme Project” with no schedule.

2. Payment account \= “Checking”; a category line Contractor Costs, amount entered at use time, Billable checked, Customer \= “Acme Co”.

3. When the contractor is actually paid, Dana opens the list, chooses Use, confirms the amount, and posts.

4. Checking decreases; Contractor Costs hits the P\&L; the billable amount is tracked against Acme Co.

5. Later, when invoicing Acme Co in the Sales module, Dana adds the tracked billable cost to the invoice; it is then marked billed (Section 12.6).

## **10.4 Automatic generation (the Job's path)**

1. At the daily run, the Job selects active Scheduled and Reminder templates whose Next Date (minus any days-in-advance) is today or earlier, in the company time zone.

2. For each Scheduled template it posts an expense with the occurrence date, writes the journal entry against the payment account, links the expense to the template, and records an occurrence.

3. For each Reminder template it raises a reminder item instead of posting.

4. It advances Previous/Next Date, honoring month-end and end conditions, and emits run metrics.

5. Any occurrence that cannot post (e.g., a deleted account) is failed in isolation, logged, and alerted — the rest of the run proceeds (Section 11.6).

## **10.5 Edit or delete a template**

1. The user opens a template, changes a line amount or the interval, and saves; Next Date recomputes if the schedule changed.

2. Expenses already posted are untouched; only future occurrences reflect the change.

3. If the user deletes instead, they confirm; future generation stops, posted expenses remain, and the action is audited.

# **11\. Business Rules & Scheduling Engine**

The scheduling engine decides when each expense is due and is shared with the Recurring Bill module. This section states the rules precisely so behavior is deterministic and testable. All date math uses the company's configured time zone and calendar (date-only) semantics.

## **11.1 Frequency & next-date algorithm**

A schedule is frequency \+ an “every N” multiplier \+ a position (day-of-month or weekday). The next date is computed from the last occurrence (or the start date for the first run).

* **Daily:** next \= last \+ N days.

* **Weekly:** next \= the configured weekday(s) in the week that is N weeks after the last.

* **Monthly:** next \= the configured day-of-month in the month that is N months after the last, clamped to month end (11.2).

* **Yearly:** next \= the configured month \+ day in the year that is N years after the last, clamped for Feb 29\.

## **11.2 Month-end clamping**

| Rule If the configured day-of-month does not exist in a target month (e.g., the 31st in February), the occurrence falls back to the last valid day of that month. A template set to the 31st posts on Feb 28 (or 29 in a leap year), Apr 30, and so on. The configured day is preserved for months that do have it. |
| :---- |

## **11.3 Days-in-advance (Scheduled)**

A Scheduled template may post N days before its transaction date. The engine treats the transaction (occurrence) date as the accounting date; the creation may happen up to N days earlier. Formally: create\_on \= occurrence\_date − days\_in\_advance, and the posted expense carries occurrence\_date as its date. N \= 0 posts on the date itself.

## **11.4 Reminder lead time**

A Reminder template raises its item N days before the transaction date: remind\_on \= occurrence\_date − remind\_days\_before. The reminder persists until the user posts the expense or the occurrence is otherwise resolved. No expense posts automatically.

## **11.5 Start & end conditions**

| Setting | Behavior |
| :---- | :---- |
| Start date | The first date considered. No occurrence is generated for a date before today at creation time. |
| End \= None | The template runs indefinitely until stopped or deleted. |
| End \= By date | The last occurrence is on or before the end date; nothing generates after it. |
| End \= After N occurrences | Generation stops once N expenses/reminders have been produced; a counter tracks progress. |

## **11.6 The Generation Job**

A background process runs at least daily and turns due templates into posted expenses or reminders. Correctness must not depend on how often it runs.

### **11.6.1 Selection & timing**

* Runs at least once per day at the company's configured local time; may run more frequently.

* Selects active (not ended, not deleted) Scheduled and Reminder templates whose next occurrence (accounting for days-in-advance) is due today or earlier.

### **11.6.2 Idempotency & exactly-once**

| Exactly-once posting Each occurrence is keyed by a unique (template\_id, occurrence\_date) record. Before posting, the Job checks this key; if it already exists, the occurrence is skipped. This guarantees a given period can never post two expenses — even if the Job runs twice, overlaps, or retries after a crash. |
| :---- |

### **11.6.3 Catch-up after downtime**

* If the Job was down and several occurrences are now overdue, it processes each missed occurrence in chronological order (subject to the safeguard below).

* A configurable safeguard can cap catch-up (e.g., collapse many missed dailies) to avoid a flood of postings; the policy is explicit and logged.

### **11.6.4 Failure handling**

* An occurrence that cannot post (deleted account, invalid payment account, validation error) is failed in isolation, recorded with a reason, and alerted — never dropped silently.

* Healthy templates in the same run are unaffected; failed occurrences can be retried or surfaced for a human to fix.

* Per-run metrics (processed / skipped / failed / duration) are emitted for monitoring (Section 20).

## **11.7 Editing rules (future-only)**

* Editing a template changes future occurrences only; expenses already posted are never rewritten.

* Changing the interval or start date recomputes Next Date on save.

* If a shared payee, item, or account referenced by the template was changed elsewhere, the user is warned before saving so the impact is clear.

# **12\. Accounting: Journal Entries, Posting & Ledger Impact**

This section is the accounting contract for the feature. It states exactly what each generated expense posts to the general ledger, how the payment account and lines map to debits and credits, how billable costs and tax are treated, and how the transaction flows into registers, the P\&L, and the balance sheet. Because an expense moves real money at the moment it posts, this behavior must be exact and identical to a hand-entered expense.

## **12.1 The accounting model for a direct expense**

An expense is a paid transaction. It posts a single, balanced double-entry journal at its transaction (occurrence) date:

* **Debits** — each category line debits its account (an expense or asset account); each item line debits the account its product/service maps to; purchase/input tax, if any, debits the configured tax account.

* **Credit** — the single Payment account is credited for the total. If it is a bank account, its asset balance decreases; if it is a credit-card account, its liability balance increases.

| No Accounts Payable, ever An expense never posts to Accounts Payable and has no due date. The money has already moved, so there is no liability to a vendor and no second “pay” step. This is the fundamental difference from a Bill, which debits the same expense accounts but credits Accounts Payable and is settled later by a separate bill payment. |
| :---- |

The general rule, for any expense:

| General posting rule Dr   Expense / item / tax accounts        \= total of all lines (+ tax)          Cr   Payment account (bank or card)   \= same total Invariant:  sum(debits) \== sum(credits)   (the entry always balances) |
| :---- |

## **12.2 Journal entry — simple bank expense**

A $74.36 monthly software subscription paid from Checking. One category line, no tax, not billable.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Software Subscriptions (Expense) | $74.36 |  |
| Checking (Bank) |  | $74.36 |
| **Total** | **$74.36** | **$74.36** |

*Effect: Checking decreases by $74.36; Software Subscriptions expense increases by $74.36 on the P\&L.*

## **12.3 Journal entry — credit-card expense**

A $120.00 utility paid on the Business Credit Card. The credit lands on a liability account, not a bank account.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Utilities (Expense) | $120.00 |  |
| Business Credit Card (Liability) |  | $120.00 |
| **Total** | **$120.00** | **$120.00** |

*Effect: the credit-card liability increases by $120.00; Utilities expense increases by $120.00. Cash is unaffected until the card is later paid down (a separate transaction outside this feature).*

## **12.4 Journal entry — split (multi-line) expense**

A single $980.00 payment from Checking split across two accounts — Rent $900 and Internet $80.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Rent (Expense) | $900.00 |  |
| Internet (Expense) | $80.00 |  |
| Checking (Bank) |  | $980.00 |
| **Total** | **$980.00** | **$980.00** |

*Effect: two expense accounts increase; Checking decreases once by the combined total. Multiple debit lines, one credit to the payment account.*

## **12.5 Journal entry — expense with purchase tax**

A $100.00 office-supplies purchase from Checking with $10.00 recoverable input tax (behavior depends on the company's tax configuration; shown here split to a tax-receivable account).

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Office Supplies (Expense) | $100.00 |  |
| Tax Receivable / Input Tax (Asset) | $10.00 |  |
| Checking (Bank) |  | $110.00 |
| **Total** | **$110.00** | **$110.00** |

*Where tax is not separately recoverable, the tax is included in the expense line instead. Pilucent defers to the existing Tax engine and the company's setup to decide which treatment applies.*

## **12.6 Billable / reimbursable expenses**

When a line is marked Billable and tied to a Customer, the cost is recoverable. This is a two-stage flow: the expense posts now; the recovery happens when the customer is invoiced.

### **Stage 1 — when the expense posts**

A $200.00 contractor cost paid from Checking, billable to Acme Co. It posts like any expense, and the amount is additionally tracked as billable to that customer.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Contractor Costs (Expense) | $200.00 |  |
| Checking (Bank) |  | $200.00 |
| **Total** | **$200.00** | **$200.00** |

*The line is flagged billable to Acme Co and appears in the pool of un-invoiced billable costs; no revenue is recognized yet.*

### **Stage 2 — when the customer is invoiced**

Later, the billable cost is added to an Acme Co invoice in the Sales module (optionally with markup). Invoicing recognizes the income and marks the line billed.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Accounts Receivable (Asset) | $200.00 |  |
| Reimbursable / Billable Income |  | $200.00 |
| **Total** | **$200.00** | **$200.00** |
| **Configuration note** Some companies recognize reimbursable income to a dedicated income account (as above); others net the recovery against the original expense. The exact income account and any markup follow the company's billable-expense settings in the Sales/Tax configuration. The recurring feature's job is to capture the billable line accurately each period so it is available to invoice — and to mark it billed once recovered so it is never double-counted. |  |  |

## **12.7 Ledger & register impact**

| Where | Impact of a posted expense |
| :---- | :---- |
| Payment account register | A new posted line appears immediately in the bank or credit-card register on the transaction date — unlike a bill, which sits in A/P until paid. |
| Profit & Loss | The debited expense accounts increase; the cost appears in the period of the transaction date. |
| Balance Sheet | A bank payment reduces a cash asset; a credit-card payment increases a liability. Recoverable input tax sits as an asset until offset. |
| Accounts Payable | No effect — an expense never touches A/P. |
| Billable pool | Any billable line is added to the customer's un-invoiced billable costs (off the P\&L until invoiced). |
| Vendor reports | Because it is not a bill, an expense shows in “transactions by payee” style reports rather than vendor-balance (A/P) reports. |

## **12.8 How recurring generation posts**

* Each generated expense posts the same journal entry shape as its template, stamped with that occurrence's transaction date — so the cost lands in the correct accounting period.

* Scheduled templates post automatically on the due date (or up to N days in advance, still dated the occurrence date). Reminder and Unscheduled templates post only when a human acts.

* Posting is exactly-once per occurrence (Section 11.6.2), so a period can never be double-posted to the ledger.

* If the payment account or a line account is missing/invalid at post time, the occurrence fails in isolation and is surfaced — the ledger is never left half-posted.

## **12.9 Reconciliation & audit**

* **Reconciliation.** Because a generated expense posts straight to the bank/card register, it participates in reconciliation. If a Scheduled amount differs from the real charge (common for variable spend), the register line won't match the statement — which is exactly why variable costs should use the Reminder type. This is a reconciliation consideration, not a defect.

* **Audit trail.** Every automatic posting is written to the audit log as a system action with the template link, occurrence date, accounts, and amounts, so each generated expense is traceable back to its template and run.

* **Editing history.** Template edits never rewrite posted expenses or completed reconciliations; corrections to a posted expense are made on that expense (or by a reversal), not by editing the template.

## **12.10 Reversals & deletions**

* Deleting a template stops future generation but does not remove or reverse expenses already posted — those remain in the ledger and on any completed reconciliation.

* To undo a specific posted expense, the user deletes or voids that expense (subject to permissions and period locks), which reverses its journal entry; the template is unaffected.

* If a posted expense had a billable line that was already invoiced, unwinding it follows the standard credit-note/void rules in the Sales module so income and A/R stay consistent.

# **13\. Data Model**

The data model stores templates, their schedule, their lines, and the occurrences they produce. It is shared in shape with the Recurring Bill module; the expense-specific fields are the payment account and payment method, and the absence of any terms/due-date. Field tables list name, type, nullability, and notes. All records are scoped by company\_id (tenant).

## **13.1 recurring\_template**

The template header — identity, type, payee, payment, and denormalized run state.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Template identifier. |
| company\_id | UUID (FK) | No | Owning tenant; every query is scoped by it. |
| name | text | No | Template name; unique per company (case-insensitive). |
| txn\_type | enum | No | expense in v1 (engine supports more later). |
| type | enum | No | scheduled | reminder | unscheduled. |
| payee\_id | UUID (FK) | Yes | Vendor/Payee master reference (“Who did you pay?”). |
| payment\_account\_id | UUID (FK) | No | Bank or credit-card account credited on posting — required. |
| payment\_method | enum | Yes | cash | check | credit\_card | eft, etc. Metadata. |
| memo | text | Yes | Note copied to generated expenses. |
| attachment\_id | UUID (FK) | Yes | Single reference file on the template (≤ 20 MB). |
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
| **Contrast with recurring\_bill** The bill template carries a terms\_id (payment terms) that drives a due date on each generated bill. The expense template has no terms and no due date; instead it carries payment\_account\_id and payment\_method. This single difference is what makes one post to Accounts Payable and the other post straight to a bank/card. |  |  |  |

## **13.2 recurring\_schedule (fields / value object)**

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

## **13.3 recurring\_template\_line**

One row per category or item line. Drives the debit side of the journal entry and billable tracking.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Line identifier. |
| template\_id | UUID (FK) | No | Parent template. |
| line\_type | enum | No | category | item. |
| account\_id | UUID (FK) | Yes | Account debited (category lines). |
| product\_service\_id | UUID (FK) | Yes | Product/Service (item lines); maps to an account \+ tax. |
| description | text | Yes | Line description copied to the expense. |
| quantity | decimal(19,4) | Yes | Item lines. |
| rate | decimal(19,4) | Yes | Item lines. |
| amount | decimal(19,4) | No | Line amount; sums to total. |
| is\_billable | boolean | No | Default false; if true, customer\_id required. |
| customer\_id | UUID (FK) | Yes | Customer a billable line is recovered from. |
| tax\_code\_id | UUID (FK) | Yes | Tax code applied per the Tax engine. |
| sort\_order | int | No | Row order. |

## **13.4 recurring\_occurrence**

One row per due date the engine acts on. The unique key guarantees exactly-once posting; it also powers the Reminders List (rows where status \= reminded and resolved\_at is null).

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Occurrence identifier. |
| template\_id | UUID (FK) | No | Parent template. |
| occurrence\_date | date | No | Transaction/accounting date for this run. |
| status | enum | No | posted | reminded | failed | skipped. |
| generated\_expense\_id | UUID (FK) | Yes | The posted expense (when status \= posted). |
| resolved\_at | timestamptz | Yes | When a reminder was acted on / occurrence closed. |
| error | text | Yes | Failure reason (when status \= failed). |
| created\_at | timestamptz | No | When the occurrence was recorded. |
| UNIQUE(template\_id, occurrence\_date) | constraint | — | Enforces exactly-once posting per period. |

## **13.5 New columns on the expense record**

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| source\_template\_id | UUID (FK) | Yes | Links a generated expense back to its template. |
| source\_occurrence\_id | UUID (FK) | Yes | Links to the specific occurrence that produced it. |

*These links let reports and audits attribute any expense to its recurring source and run, and let the system detect whether an occurrence already posted.*

## **13.6 Sample template (JSON)**

| recurring\_template (expense) {   "id": "tmpl\_9f2",   "txn\_type": "expense",   "type": "scheduled",   "name": "Design Software — Monthly",   "payee\_id": "pay\_pixelworks",   "payment\_account\_id": "acct\_business\_cc",   "payment\_method": "credit\_card",   "create\_days\_in\_advance": 0,   "schedule": {     "frequency": "monthly", "interval\_count": 1,     "day\_mode": "day\_of\_month", "day\_of\_month": 1,     "start\_date": "2026-08-01", "end\_type": "none"   },   "lines": \[     { "line\_type": "category", "account\_id": "acct\_software",       "description": "Team subscription", "amount": 49.00,       "is\_billable": false }   \],   "memo": "Auto-charged to card",   "total\_amount": 49.00,   "next\_run\_date": "2026-08-01" } |
| :---- |

# **14\. API Specification**

The feature exposes a small, REST-style API. All endpoints are tenant-scoped and permission-checked server-side (Section 17). Requests and responses are JSON; money is decimal in base currency; dates are calendar dates. Only representative endpoints and payloads are shown.

## **14.1 Endpoint summary**

| Method & path | Purpose | Notes |
| :---- | :---- | :---- |
| GET /api/v1/recurring-templates | List templates | Supports q (name), type, txn\_type, sort, and pagination. |
| POST /api/v1/recurring-templates | Create a template | Validates schedule, payment account, and lines; computes next\_run\_date. |
| GET /api/v1/recurring-templates/{id} | Fetch one | Full template with schedule and lines. |
| PUT /api/v1/recurring-templates/{id} | Edit a template | Future-only; recomputes next\_run\_date if schedule changed. |
| DELETE /api/v1/recurring-templates/{id} | Delete a template | Stops future generation; posted expenses untouched. |
| POST /api/v1/recurring-templates/{id}:use | Use now | Posts or drafts an expense from the template. |
| GET /api/v1/recurring-reminders | List due reminders | Powers the Reminders List; q and txn\_type filters. |
| POST /api/v1/recurring-reminders/{id}:post | Resolve a reminder | Posts the expense for a reminder occurrence. |

## **14.2 List templates**

| Request / response GET /api/v1/recurring-templates?txn\_type=expense\&sort=next\_run\_date\&page=1 200 OK {   "data": \[     { "id": "tmpl\_9f2", "name": "Design Software — Monthly",       "type": "scheduled", "txn\_type": "expense",       "interval": "Every Month on the 1st",       "payee": "Pixelworks", "payment\_account": "Business Credit Card",       "previous\_run\_date": null, "next\_run\_date": "2026-08-01",       "amount": 49.00 }   \],   "page": 1, "page\_size": 25, "total": 1 } |
| :---- |

## **14.3 Create template**

| Request / responses POST /api/v1/recurring-templates {   "name": "Electricity",   "txn\_type": "expense",   "type": "reminder",   "payee\_id": "pay\_citypower",   "payment\_account\_id": "acct\_checking",   "payment\_method": "eft",   "remind\_days\_before": 3,   "schedule": { "frequency": "monthly", "interval\_count": 1,                  "day\_mode": "day\_of\_month", "day\_of\_month": 5,                  "start\_date": "2026-08-05", "end\_type": "none" },   "lines": \[ { "line\_type": "category", "account\_id": "acct\_utilities",                "description": "Monthly power", "amount": 0,                "is\_billable": false } \],   "memo": "Amount varies" } 201 Created  → returns the full template with server-computed next\_run\_date and total\_amount. 422 Unprocessable Entity  → validation errors, e.g.: { "errors": \[    { "field": "payment\_account\_id", "code": "required" },    { "field": "schedule.start\_date", "code": "required\_for\_reminder" },    { "field": "lines\[0\].customer\_id", "code": "required\_when\_billable" } \] } |
| :---- |

## **14.4 Use a template now**

Body may include a mode flag: draft (return an editable expense payload without posting) or post (create and post the expense immediately). Default: draft for Reminder/Unscheduled, post for Scheduled. Returns the created or draft expense, linked via source\_template\_id, with the payment account and lines resolved so the caller can preview the journal entry.

## **14.5 List & resolve reminders**

| Reminders API GET /api/v1/recurring-reminders?q=electric\&txn\_type=expense → due reminder occurrences with template, payee, expected amount, date. POST /api/v1/recurring-reminders/{occurrence\_id}:post { "amount\_overrides": \[ { "line\_id": "ln\_1", "amount": 128.40 } \] } → posts the expense for that occurrence and marks the reminder resolved. |
| :---- |

## **14.6 Error model**

* Validation errors return 422 with a list of { field, code } so the UI can highlight the exact field.

* Permission failures return 403; missing templates return 404; all responses are tenant-scoped.

* Generation is idempotent server-side: a repeated post for the same occurrence returns the existing expense rather than creating a duplicate.

# **15\. Integration with Other Modules**

The feature is not standalone — it reuses and updates existing parts of Pilucent. This section lists every connection and what flows across it, so engineers know what they touch and QA knows what to regression-test.

| Module | How the feature connects to it |
| :---- | :---- |
| Chart of Accounts | Category lines post to expense/asset accounts; the payment account is a bank or credit-card account. Deleting/merging an account must be handled (Section 16). |
| Bank & Credit Card accounts | The payment account is credited on every generated expense; its register gains a posted line and its balance updates immediately. |
| Payee / Vendor master | Supplies “Who did you pay?” and defaults; generated expenses reference the payee for transaction-by-payee reporting. |
| Products & Services | Item lines reference a product/service that maps to an account and default tax. |
| Tax engine | Computes purchase/input tax on lines per company configuration; determines whether tax splits to a tax account or is embedded. |
| Customers | Billable lines tie a recoverable cost to a customer. |
| Sales / Invoicing | Billable amounts captured here become available to add to that customer's invoice; once invoiced they are marked billed (Section 12.6). |
| General Ledger / posting | Receives the balanced journal for each generated expense (Section 12); the single source of truth for balances and reports. |
| Reports | Generated expenses flow into P\&L, spending, cash/card registers, and transaction-by-payee reports automatically via their ledger postings. |
| Audit log | Template create/edit/delete, Use, and every automatic posting are recorded with actor (or “system”), timestamp, and before/after. |
| Notifications | Reminders and exception alerts are delivered through the existing notification service (Section 19). |
| Background job runner | Executes the Generation Job on the company's schedule (Section 11.6). |

# **16\. Edge Cases, Validation & Error Handling**

Recurring, self-posting money is unforgiving of ambiguity. This section lists the validation the form enforces, the behavioral edge cases the engine must handle, and the principles for surfacing errors.

## **16.1 Validation rules (form & API)**

| Rule | Behavior |
| :---- | :---- |
| Template name required & unique | Non-empty; unique per company (case-insensitive). |
| Payment account required | An expense must name a bank or credit-card account to credit. |
| Type-conditional schedule | Scheduled/Reminder require interval \+ start \+ end; Unscheduled forbids them. |
| Days-in-advance / remind-before range | Integer 0–90; shown only for the relevant type. |
| Billable requires customer | A line marked Billable must have a Customer; otherwise the save is rejected. |
| At least one line | A template must have at least one category or item line with an account. |
| Amounts | Non-negative; total is the sum of lines \+ tax; item lines require qty × rate. |
| End settings | end\_type \= by\_date needs a date; after\_count needs N ≥ 1\. |
| Attachment size | ≤ 20 MB; larger files rejected with a clear message. |
| Start not in the past (at creation) | Occurrences are not generated for dates before today when the template is created. |

## **16.2 Behavioral edge cases**

| Situation | Expected behavior |
| :---- | :---- |
| Day-of-month \> days in month | Clamp to the last day of that month (e.g., 31st → Feb 28/29). |
| Payment account deleted/closed | Block or warn on save; at post time the occurrence fails in isolation and is alerted — the ledger is never half-posted. |
| Line account deleted/merged | Warn on edit; failed occurrences surface for correction rather than posting to a missing account. |
| Closed/locked accounting period | An occurrence dated in a locked period cannot post; it is failed and surfaced so the user can adjust the date or reopen the period. |
| Credit-card vs bank payment account | Same flow; the credit is a liability increase (card) or asset decrease (bank) — the posting adapts automatically (Section 12). |
| Billable line already invoiced | Marked billed; not offered again for recovery. Unwinding follows Sales credit-note rules. |
| Job downtime / catch-up | Missed occurrences are caught up in order, subject to the catch-up safeguard; no duplicates (unique occurrence key). |
| Duplicate run / overlap | Exactly-once key prevents a second posting for the same occurrence date. |
| Zero-amount reminder | Allowed — a Reminder placeholder amount of 0 is expected; the real amount is entered before posting. |
| Time-zone / DST boundary | Due-date math uses the company time zone and date-only semantics, so a bill dated the 1st is the 1st regardless of the worker's location or DST. |
| Editing mid-cycle | Applies to future occurrences only; the current posted expense is unchanged. |

## **16.3 Error-handling principles**

* Fail one occurrence, not the run: a single bad occurrence never blocks healthy templates.

* Never post half an entry: if any part of the journal can't post, the whole occurrence fails and is surfaced.

* Prefer skip-and-alert over guess: when unsure (missing account, locked period), fail the occurrence with a clear reason rather than posting something wrong.

* Every failure is visible: failures are logged, alerted, and retriable — never silent.

# **17\. Permissions & Roles**

Access follows the platform's existing role model and is enforced server-side on every endpoint; the UI hides or disables actions the current role cannot perform. Because generated expenses move money, posting-related capabilities are held more tightly than viewing.

| Capability | Admin | Accountant | Bookkeeper | Payments Clerk | Viewer |
| :---- | :---- | :---- | :---- | :---- | :---- |
| View templates & reminders | ✔ | ✔ | ✔ | ✔ | ✔ |
| Create / edit templates | ✔ | ✔ | ✔ | ✔ | — |
| Delete templates | ✔ | ✔ | ✔ | — | — |
| Use / post expense from template | ✔ | ✔ | ✔ | ✔ | — |
| Process reminders | ✔ | ✔ | ✔ | ✔ | — |
| Choose / change payment account | ✔ | ✔ | ✔ | ✔ | — |
| Mark lines billable / set customer | ✔ | ✔ | ✔ | — | — |
| Void / delete a posted expense | ✔ | ✔ | — | — | — |

All endpoints enforce these permissions server-side; the UI hides or disables actions the current role cannot perform. Voiding a posted expense is restricted because it reverses a ledger entry.

# **18\. Non-Functional Requirements**

Because recurring expenses run unattended and post money, the module is held to explicit bars for performance, reliability, security, and correctness across time zones. Each requirement is written so QA can turn it into a measurable test.

## **18.1 Performance**

| Area | Requirement | Target |
| :---- | :---- | :---- |
| List page load | Recurring Transactions list renders the first page | ≤ 1.5 s (p95) for ≤ 500 templates |
| Template save | Create/update a template and recompute Next Date | ≤ 800 ms (p95) |
| Reminders List load | Query and render due reminder items | ≤ 1.5 s (p95) |
| Use / post one expense | Materialize and post an expense (write the journal) | ≤ 1 s (p95) |
| Generation throughput | Expenses posted per minute per worker | ≥ 2,000 occurrences/min |
| Job window | Full daily sweep for a large tenant | ≤ 10 min for 50k active templates |

## **18.2 Scalability & multi-tenancy**

* **Tenant isolation.** Every query, job selection, posting, and API response is scoped by company\_id; no cross-tenant read or write is possible, enforced in the data-access layer.

* **Horizontal scale.** The Generation Job is shardable by company\_id so multiple workers run in parallel without contention.

* **Indexing.** next\_run\_date, company\_id, status, and (template\_id, occurrence\_date) are indexed to keep interactive queries and job selection fast.

## **18.3 Reliability & correctness**

* **Generation reliability ≥ 99.9%.** Of all templates due on a day, at least 99.9% post on time; the rest catch up on the next run.

* **Exactly-once posting.** The unique (template\_id, occurrence\_date) key guarantees a period can never post two expenses to the ledger.

* **Balanced entries only.** Every posted journal has equal debits and credits or it does not post at all — the ledger is never left inconsistent.

* **No silent loss.** A failed occurrence is recorded, alerted, and retriable; it is never dropped.

## **18.4 Security & privacy**

* **Authorization on every call.** Server-side permission checks (Section 17\) gate every template and posting action.

* **Attachment safety.** Template attachments (≤ 20 MB) are virus-scanned, access-controlled to the owning company, and served via signed, expiring URLs.

* **Encryption.** All traffic is TLS; records and attachments are encrypted at rest per platform standards.

* **Least-privilege job.** The worker runs with a scoped identity able to post expenses and write occurrences/audit — nothing more.

## **18.5 Time zones, dates & i18n**

* **Company-local scheduling.** All due-date math, days-in-advance, reminder offsets, and “today” comparisons use the company time zone.

* **Date-only posting.** Occurrence dates are calendar dates, so a generated expense lands in the intended accounting period regardless of worker location.

* **Locale & translation.** Amounts/dates render in the company locale; all labels and copy are externalized for localization.

## **18.6 Availability & observability**

* Interactive endpoints target the platform's standard availability SLO; a job outage delays posting but never loses it (catch-up guarantees eventual completion).

* The job emits structured metrics (processed / skipped / failed / duration) and logs per run, with alerting when failures or run duration cross a threshold.

* A dead-letter path captures occurrences that fail repeatedly so on-call can remediate without blocking healthy templates.

# **19\. Notifications**

Notifications keep users informed without pulling them into the app, and distinguish reminders that need a decision from confirmations that automation ran. They respect the user's global preferences.

## **19.1 Reminder notifications (Reminder templates)**

* **Trigger.** On a Reminder template's computed reminder date (transaction date minus “remind N days before”).

* **Content.** Template name, payee, expected amount, transaction date, and a direct link to review and post the expense.

* **Grouping.** Multiple reminders due the same day may be rolled into one digest; each still links to its item.

* **Lifecycle.** Once the expense is posted, the reminder clears and no further nudges are sent for that occurrence.

## **19.2 Generation summaries (optional, Scheduled templates)**

Scheduled expenses post automatically, so they need confirmation rather than a call to action. Summaries are optional and off by default to avoid inbox fatigue.

* An optional periodic digest listing expenses the engine posted: payee, amount, payment account, date, and a link to each.

* Immediate alerts are reserved for exceptions (see 19.3).

## **19.3 Failure & exception alerts**

| Exceptions always surface Even with summaries disabled, a failed posting (invalid or closed payment account, deleted line account, locked period, validation error) raises an alert to an authorized user with the reason and a link to the template. Silent failure is never acceptable for money that should have posted. |
| :---- |

## **19.4 Channels & preferences**

| Channel | Used for | Default |
| :---- | :---- | :---- |
| In-app / bell | Reminders, generation summaries, exceptions | On |
| Email | Reminders and exception alerts; optional summaries | On for reminders/exceptions |
| Digest roll-up | Multiple same-day reminders or posted-expense lists | On (grouped) |
| Billable nudge | Optional: billable costs awaiting invoicing for a customer | Off (opt-in) |

* Recipients follow role and per-template responsibility; users who can post the template receive its reminders/exceptions.

* All types honor the user's global preferences; transactional exception alerts may be non-optional by policy.

# **20\. Analytics & Reporting**

Two audiences consume data from this module: end users, who need to see and manage recurring spend, and the product/engineering team, who need to know whether the feature delivers value and posts reliably — all without exposing one tenant's data to another.

## **20.1 User-facing report — Recurring Templates**

* Grouped by Type (Scheduled / Reminder / Unscheduled), with per-group and overall counts.

* Columns: Template Name, Payee, Payment account, Interval, Previous Date, Next Date, Amount, and Status.

* Shows total committed monthly/annual outflow where amount and cadence are known, to support cash-flow planning.

* A billable view lists recurring billable lines and their un-invoiced amounts per customer.

| Cross-module reporting Because generated expenses are ordinary expenses linked to their template (source\_template\_id), existing P\&L, spending, and bank/card register reports include them automatically — and the template link attributes any expense back to its recurring source. |
| :---- |

## **20.2 Product instrumentation & success metrics**

These events feed the success metrics in Section 3.4 (adoption, automation rate, billable capture, generation reliability, error rate). They are aggregated for analytics and contain no sensitive detail beyond what analytics requires.

| Event | Fires when | Key properties |
| :---- | :---- | :---- |
| template\_created | A template is saved | type, interval, payment\_account\_type, line\_count, has\_billable |
| template\_edited | A template is updated | changed\_fields, type |
| template\_deleted | A template is deleted | type, age\_days, occurrences\_generated |
| expense\_generated | The job posts a Scheduled expense | template\_id, occurrence\_date, amount, account\_type, latency |
| reminder\_raised | A reminder becomes due | template\_id, txn\_date |
| reminder\_actioned | An expense is posted from a reminder | template\_id, time\_to\_action |
| billable\_captured | A billable line posts | customer\_id, amount |
| billable\_invoiced | A billable line is added to an invoice | customer\_id, days\_to\_recover |
| job\_run | A generation sweep completes | processed, skipped, failed, duration\_ms |

## **20.3 Operational dashboards**

* Reliability: on-time posting rate, job duration, failed/dead-lettered occurrences — against the 99.9% bar.

* Adoption & automation: companies with ≥ 1 template, templates per company, and the share of recurring expenses posted by the job vs. manually.

* Cost recovery: billable amount captured vs. invoiced, and time-to-recover.

* Health: expenses reversed/voided within 48 hours of posting (the error-rate guardrail), watched for regressions after releases.

# **21\. QA & Acceptance Checklist**

This checklist turns the acceptance criteria (Section 8), scheduling rules (Section 11), accounting (Section 12), and edge cases (Section 16\) into concrete, testable items. Every box must be verifiable before the module ships.

## **21.1 List, create & schedule**

| \# | Test |
| ----- | :---- |
| 1 | List shows Template Name, Type, Txn Type, Interval, Previous Date, Next Date, Payee, Amount, and Action; sorting and name-filter work. |
| 2 | “New” opens Select Transaction Type; Expense opens the template form; Cancel returns unchanged. |
| 3 | Scheduled shows “Create \_\_ days in advance”; interval/start/end required; first Next Date computed correctly. |
| 4 | Reminder shows “Remind \_\_ days before”; nothing posts automatically; item appears on the reminder date. |
| 5 | Unscheduled hides schedule fields and never posts on its own. |
| 6 | Daily / weekly / monthly / yearly and “every N” each produce the correct Next Date; month-end clamps (31st → Feb 28/29). |
| 7 | End conditions None / By date / After N each stop generation at the right point. |

## **21.2 Payment, lines & billable**

| \# | Test |
| ----- | :---- |
| 8 | Payment account is required; the form offers bank and credit-card accounts; no terms/due-date field is shown. |
| 9 | Payment method is optional metadata and does not change the posting on its own. |
| 10 | Category and Item lines add/remove correctly; running Total matches the sum of lines \+ tax. |
| 11 | A line marked Billable requires a Customer; saving without one is rejected. |
| 12 | Memo and a single attachment (≤ 20 MB) save; oversize files are rejected clearly. |

## **21.3 Accounting & ledger (Section 12\)**

| \# | Test |
| ----- | :---- |
| 13 | A bank-account expense debits the category/item accounts and credits the bank; the bank balance decreases and the register shows the line immediately. |
| 14 | A credit-card expense credits the card liability (balance increases) instead of a bank account. |
| 15 | A split expense posts multiple debit lines against one credit to the payment account; the entry balances. |
| 16 | Purchase tax posts per the Tax engine (split to a tax account or embedded, per configuration). |
| 17 | No expense ever posts to Accounts Payable and none has a due date. |
| 18 | A billable line records amount \+ customer at posting; adding it to that customer's invoice recognizes income and marks it billed (no double recovery). |
| 19 | The generated expense appears on the P\&L in the occurrence-date period; the entry is stamped with the occurrence date. |
| 20 | An occurrence dated in a locked period, or with a deleted/closed payment or line account, fails in isolation and is alerted — never half-posted. |

## **21.4 Generation, actions & integrity**

| \# | Test |
| ----- | :---- |
| 21 | “Create N days in advance” posts N days early but dates the expense on its occurrence date. |
| 22 | Running the job twice for the same day never creates a duplicate (unique occurrence key holds). |
| 23 | A delayed job catches up missed occurrences (subject to the safeguard) without duplicating. |
| 24 | All date math uses the company time zone; a bill dated the 1st is the 1st regardless of worker location. |
| 25 | Use posts a linked expense to the payment account and (for Scheduled) advances Previous/Next Date. |
| 26 | Duplicate creates an independent “Copy of …” with empty run history; editing it never affects the original. |
| 27 | Delete stops future generation, leaves posted expenses and completed reconciliations untouched, and writes an audit entry. |
| 28 | Editing a template never rewrites posted expenses; only future occurrences reflect the change. |
| 29 | Reminders List shows due items, supports find/filter, allows amount override, and clears an item once posted. |
| 30 | Permissions are enforced server-side per the Section 17 matrix; every posting and template change is audited. |
| **Definition of done** All 30 checks pass across the three template types and both payment-account kinds (bank and credit card); performance targets in 18.1 are met at p95; every generated expense posts a balanced journal to the correct accounts; and no cross-tenant access is possible in any list, API, posting, or job path. |  |

# **22\. Future Enhancements**

The v1 scope is focused on recurring Expenses, but the engine, data model, and UI are built to extend. Items are sequenced roughly by value and effort; several were non-goals in Section 3.3 and have reserved room in the schema.

## **22.1 More recurring transaction types**

The template, schedule, and generation engine are transaction-type agnostic. Adding a type is mainly a type-specific form and posting adapter.

* **Recurring Bill (companion).** Already specified separately; posts to Accounts Payable with terms.

* **Recurring Check.** A close cousin of the expense that also prints/records a check number.

* **Recurring Invoice / Sales Receipt.** The sales-side counterparts, with optional send-on-generate.

* **Recurring Journal Entry.** For accruals, depreciation, and allocations on a schedule.

## **22.2 Lifecycle controls**

* **Pause / Resume.** Temporarily halt posting without deleting the template (schema reserves a paused state).

* **Skip next.** Skip a single upcoming occurrence and continue after.

* **End early / extend.** Adjust the end condition on a running template with a Next-Date preview.

## **22.3 Banking, recovery & scale**

* **Bank-feed auto-match.** Automatically match generated expenses to the real bank/card charges in the feed, easing reconciliation of variable spend.

* **Billable markup rules.** Apply a default markup when a billable recurring cost is invoiced to a customer.

* **Approval workflow.** Optional sign-off before a generated expense posts, for companies that require it.

* **Bulk import/export & bulk edit.** CSV import of templates and cross-template edits.

* **Custom frequencies & multi-currency.** “Last weekday of the month” style rules and per-template currency with FX at posting time.

# **23\. Appendix**

## **23.1 Field quick-reference**

| Field | Meaning | Detail in |
| :---- | :---- | :---- |
| Template name | Human label for the recurring expense | §9.3, §13 |
| Type | Scheduled / Reminder / Unscheduled behavior | §7, §9.3, §11 |
| Payee | Who was paid (“Who did you pay?”) | §9.3, §15 |
| Payment account | Bank or card credited on posting — required | §9.3, §12 |
| Payment method | How it was paid (metadata) | §9.3 |
| Days in advance | How early a Scheduled expense posts | §9.3, §11.3 |
| Remind before | Lead time for a Reminder item | §9.3, §11.4 |
| Interval | Frequency \+ day-of-month / weekday \+ every-N | §9.3, §11.1 |
| Billable / Customer | Recoverable line tied to a customer | §9.3, §12.6 |
| source\_template\_id | Links a posted expense to its template | §13, §20.1 |

## **23.2 Type-behavior summary**

| Behavior | Scheduled | Reminder | Unscheduled |
| :---- | :---- | :---- | :---- |
| Auto-posts expense | **Yes** | **No** | **No** |
| Has a timetable | Yes | Yes | — |
| Appears in Reminders List | No | Yes | No |
| Uses Next Date | Yes | Yes | — |
| Primary way to post | Automatic on due date | Post from reminder | Use from the list |

## **23.3 Expense vs. Bill — accounting cheat-sheet**

|  | Expense (this module) | Bill (companion) |
| :---- | :---- | :---- |
| Debit | Category / item / tax accounts | Category / item / tax accounts |
| Credit | **Payment account (bank/card)** | **Accounts Payable** |
| When cash moves | At posting | At the later bill payment |
| Due date / terms | None | Yes |
| Second step | None | Pay bill (Dr A/P, Cr bank/card) |
| Register hit | Bank/card immediately | A/P now; bank/card on payment |

## **23.4 Change log**

| Version | Date | Change |
| :---- | :---- | :---- |
| 1.0 | Initial | First release for build: Recurring Expense with Scheduled / Reminder / Unscheduled types, mandatory payment account, direct-to-ledger posting, billable-to-customer recovery, scheduling engine, data model, APIs, and QA checklist. |

*End of document.*