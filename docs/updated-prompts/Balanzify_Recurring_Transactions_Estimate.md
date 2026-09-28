**BALANZIFY**  
**Accounting Platform  ·  Product & Engineering**

**Recurring Transactions**

**Estimate Module**

End-to-End Product Requirements & Technical Specification

*Feature goals · User stories · Functional spec · User flows · Non-posting behavior & downstream accounting · Data model · APIs*

| Field | Detail |
| :---- | :---- |
| Document title | Recurring Transactions (Estimate) — Product & Technical Requirements Document |
| Product area | Sales domain · Customer quotes / proposals · Recurring Transactions |
| Prepared for | Balanzify Product, Engineering & QA teams |
| Document type | Feature specification / build reference (developer-facing) |
| Version | 1.0 (Initial release for build) |
| Status | **Ready for development** |
| Prerequisite modules | Sales module, Invoice & Sales Receipt (for conversion), Customer master, Products & Services, Sales Tax engine, Chart of Accounts, Email/Send service, Customer Portal |
| Companion modules | Recurring Invoice (posting sibling); Recurring Purchase Order (the purchase-side non-posting analog) — all share the same scheduling engine |
| Related future work | Recurring Invoice, Recurring Sales Receipt (same engine); customer e-acceptance & deposit invoices |

# **Table of Contents**

[**Table of Contents	2**](#heading=)

[**1\. Introduction & Purpose	3**](#heading=)

[1.1 Where an estimate sits in the sales cycle	3](#heading=)

[1.2 Who this document is for	4](#heading=)

[1.3 How to read it	4](#heading=)

[**2\. Glossary & Terminology	5**](#heading=)

[**3\. Feature Goals & Objectives	6**](#heading=)

[3.1 Business goals	6](#heading=)

[3.2 User goals	6](#heading=)

[3.3 Non-goals (explicitly out of scope for v1)	6](#heading=)

[3.4 Success metrics	7](#heading=)

[**4\. Competitive Research & Market Analysis (R\&D)	8**](#heading=)

[4.1 Research method	8](#heading=)

[4.2 What the market has in common	8](#heading=)

[4.3 Where platforms differ	9](#heading=)

[**5\. Scope, Assumptions & Dependencies	11**](#heading=)

[5.1 In scope (v1)	11](#heading=)

[5.2 Out of scope (v1)	11](#heading=)

[5.3 Assumptions	11](#heading=)

[5.4 Dependencies	12](#heading=)

[**6\. User Personas	13**](#heading=)

[6.1 Priya — Owner of a design studio (retainer clients)	13](#heading=)

[6.2 Marcus — Sales bookkeeper	13](#heading=)

[6.3 Dana — Operations manager (project bids)	13](#heading=)

[**7\. Concept Model & Feature Overview	14**](#heading=)

[7.1 Template, not a transaction	14](#heading=)

[7.2 The three types	14](#heading=)

[7.3 The estimate status lifecycle	14](#heading=)

[7.4 What makes an estimate different from an invoice or sales receipt	15](#heading=)

[7.5 Where the feature lives in Balanzify	15](#heading=)

[7.6 Template lifecycle	15](#heading=)

[**8\. User Stories & Acceptance Criteria	16**](#heading=)

[Epic A — Viewing recurring transactions	16](#heading=)

[EST-01  See all recurring templates	16](#heading=)

[EST-02  Find templates and track estimates by status	16](#heading=)

[Epic B — Creating a recurring estimate template	16](#heading=)

[EST-03  Start a new template and choose the type	16](#heading=)

[EST-04  Configure a Scheduled estimate	16](#heading=)

[EST-05  Configure a Reminder estimate	17](#heading=)

[EST-06  Configure an Unscheduled estimate	17](#heading=)

[EST-07  Name the customer, email recipients, and payment options	17](#heading=)

[EST-08  Set delivery details (addresses, ship-via, dates, store)	17](#heading=)

[EST-09  Build the quote (line items, discount, tax, shipping, messages)	18](#heading=)

[Epic C — Acting on templates	18](#heading=)

[EST-10  Use a template now	18](#heading=)

[EST-11  Email the estimate to the customer	18](#heading=)

[EST-12  Duplicate a template	18](#heading=)

[EST-13  Delete a template safely	19](#heading=)

[EST-14  Edit a template without corrupting history	19](#heading=)

[Epic D — Status, conversion & non-posting	19](#heading=)

[EST-15  Keep the estimate non-posting; accept and convert it to an invoice	19](#heading=)

[EST-16  Track, invoice, decline, and expire estimates	20](#heading=)

[**9\. Detailed Functional Specification	21**](#heading=)

[9.1 Recurring Transactions list	21](#heading=)

[9.1.1 Columns	21](#heading=)

[9.1.2 Toolbar & controls	21](#heading=)

[9.2 Select Transaction Type dialog	21](#heading=)

[9.3 Recurring estimate template form	22](#heading=)

[9.3.1 Identity & type	22](#heading=)

[9.3.2 Type-specific behavior	22](#heading=)

[9.3.3 Customer, email & online payments	23](#heading=)

[9.3.4 Schedule — interval, start & end	23](#heading=)

[9.3.5 Delivery details	24](#heading=)

[9.3.6 Line items	24](#heading=)

[9.3.7 Totals — discount, tax & shipping	24](#heading=)

[9.3.8 Customer messages	25](#heading=)

[9.3.9 Footer — attachment & actions	25](#heading=)

[9.4 Actions on templates and generated estimates	25](#heading=)

[9.5 Reminders List	26](#heading=)

[9.6 “Make recurring” from an existing estimate	26](#heading=)

[9.7 Estimates view (by status)	26](#heading=)

[**10\. User Flows	28**](#heading=)

[10.1 Create a Scheduled estimate (Priya — automatic, auto-email retainer)	28](#heading=)

[10.2 Reminder estimate (Marcus — variable scope)	28](#heading=)

[10.3 Unscheduled project bid \+ progress invoicing (Dana)	28](#heading=)

[10.4 Automatic generation & emailing (the Job's path)	29](#heading=)

[10.5 Accept → convert to invoice (the posting step)	29](#heading=)

[10.6 Progress / partial invoicing	29](#heading=)

[10.7 Decline / expire / edit / delete	29](#heading=)

[**11\. Business Rules & Scheduling Engine	30**](#heading=)

[11.1 Frequency & next-date algorithm	30](#heading=)

[11.2 Month-end clamping	30](#heading=)

[11.3 Days-in-advance (Scheduled)	30](#heading=)

[11.4 Reminder lead time	30](#heading=)

[11.5 Start & end conditions	30](#heading=)

[11.6 The Generation Job	31](#heading=)

[11.6.1 Selection & timing	31](#heading=)

[11.6.2 Idempotency & exactly-once	31](#heading=)

[11.6.3 Auto-email & failure handling	31](#heading=)

[11.7 Editing rules (future-only)	31](#heading=)

[11.8 Estimate-numbering rules	31](#heading=)

[11.9 Discount & tax computation	32](#heading=)

[11.10 Status-transition & expiry rules	32](#heading=)

[**12\. Accounting: Non-Posting Behavior & Downstream Posting	33**](#heading=)

[12.1 Why an estimate is non-posting	33](#heading=)

[12.2 How an estimate is tracked without posting	33](#heading=)

[12.3 The status lifecycle posts nothing	34](#heading=)

[12.4 Converting to an Invoice — the posting event	34](#heading=)

[12.5 Converting to a Sales Receipt (paid at once)	34](#heading=)

[12.6 Discount & sales tax on the resulting invoice	35](#heading=)

[12.7 Progress / partial invoicing	35](#heading=)

[12.8 A note on deposits & deferred revenue	35](#heading=)

[12.9 Declining, expiring & closing	35](#heading=)

[12.10 How recurring generation behaves	36](#heading=)

[**13\. Data Model	37**](#heading=)

[13.1 recurring\_template	37](#heading=)

[13.2 recurring\_schedule (fields / value object)	38](#heading=)

[13.3 recurring\_template\_line	39](#heading=)

[13.4 recurring\_occurrence	39](#heading=)

[13.5 The estimate record & its links	40](#heading=)

[13.6 Sample template (JSON)	40](#heading=)

[**14\. API Specification	41**](#heading=)

[14.1 Endpoint summary	41](#heading=)

[14.2 Create template	41](#heading=)

[14.3 Send, update status & convert	42](#heading=)

[14.4 List estimates by status	42](#heading=)

[14.5 Error model	42](#heading=)

[**15\. Integration with Other Modules	43**](#heading=)

[**16\. Edge Cases, Validation & Error Handling	44**](#heading=)

[16.1 Validation rules (form & API)	44](#heading=)

[16.2 Behavioral edge cases	44](#heading=)

[16.3 Error-handling principles	45](#heading=)

[**17\. Permissions & Roles	46**](#heading=)

[**18\. Non-Functional Requirements	47**](#heading=)

[18.1 Performance	47](#heading=)

[18.2 Scalability & multi-tenancy	47](#heading=)

[18.3 Reliability & correctness	47](#heading=)

[18.4 Security & privacy	48](#heading=)

[18.5 Time zones, dates & i18n	48](#heading=)

[18.6 Availability & observability	48](#heading=)

[**19\. Notifications	49**](#heading=)

[19.1 Reminder notifications (Reminder templates)	49](#heading=)

[19.2 Send confirmations & customer responses	49](#heading=)

[19.3 Failure & exception alerts	49](#heading=)

[19.4 Expiry & channels	49](#heading=)

[**20\. Analytics & Reporting	51**](#heading=)

[20.1 User-facing reports	51](#heading=)

[20.2 Product instrumentation & success metrics	51](#heading=)

[20.3 Operational dashboards	52](#heading=)

[**21\. QA & Acceptance Checklist	53**](#heading=)

[21.1 List, create & schedule	53](#heading=)

[21.2 Customer, email, lines, discount & tax	53](#heading=)

[21.3 Non-posting behavior & conversion (Section 12\)	53](#heading=)

[21.4 Generation, actions & integrity	54](#heading=)

[**22\. Future Enhancements	59**](#heading=)

[22.1 Customer acceptance & deposits	59](#heading=)

[22.2 Invoicing depth	59](#heading=)

[22.3 Lifecycle & scale	59](#heading=)

[**23\. Appendix	60**](#heading=)

[23.1 Field quick-reference	60](#heading=)

[23.2 Type-behavior summary	60](#heading=)

[23.3 Estimate status lifecycle	60](#heading=)

[23.4 Estimate vs Invoice vs Sales Receipt — cheat-sheet	61](#heading=)

[23.5 Conversion posting quick-reference	61](#heading=)

[23.6 The sales-side & purchase-side family	61](#heading=)

[23.7 Change log	61](#heading=)

*Tip: right-click the table above in Word and choose “Update Field” to refresh page numbers.*

# **1\. Introduction & Purpose**

This document is the complete build reference for the Recurring Estimate feature in Balanzify. It specifies, in one place, everything a product manager, engineer, or QA analyst needs to design, build, and verify the feature: why it exists, how it behaves on every screen, the rules that govern scheduling and estimate numbering, how an estimate flows through its status lifecycle, why it is non-posting, exactly what accounting happens when it is later converted into an invoice (or sales receipt), the data it stores, the APIs it exposes, and how it connects to the rest of the platform.

A recurring estimate is a saved template for a quote the business sends a customer on a regular cadence — a repeating service proposal, a standing quote for a retainer client, a periodic price bid. Instead of re-creating the same quote every period, the user sets it up once and Balanzify either creates the estimate automatically (and can email it to the customer) or reminds them to.

| The one fact that shapes this entire module An estimate is non-posting. It is a proposal to a customer — a quote of what work will cost — not an accounting event. Creating an estimate writes no journal entry and has no effect on the profit & loss, the balance sheet, income, Accounts Receivable, or sales tax. The accounting happens later, when the customer accepts and the estimate is converted into an invoice (or a sales receipt). Every rule and field here follows from that. |
| :---- |

An estimate is a sales-side, customer-facing document — the mirror image of a purchase order, which is the purchase-side, vendor-facing non-posting document. Both are proposals that post nothing until converted: a purchase order becomes a bill (Dr expense, Cr A/P); an estimate becomes an invoice (Dr A/R, Cr income). Balanzify already ships a Sales module including Invoices and Sales Receipts — the posting transactions an estimate turns into. This feature adds the recurring layer on top of the existing Estimate, reusing its form and its place in the sales cycle, and shares the same scheduling engine as the Recurring Invoice, Bill, Expense, Cheque, and Purchase Order modules.

## **1.1 Where an estimate sits in the sales cycle**

Understanding the cycle explains why the estimate is non-posting and how it connects to the rest of the platform:

| Step | What happens (and whether it posts) |
| :---- | :---- |
| 1\. Estimate / quote | **Non-posting.**   |
| 2\. Customer accepts | The customer approves the quote (via email/portal or verbally). |
| 3\. Invoice / Sales Receipt | **Posting.**   |
| 4\. Payment | The invoice is paid later by the customer; a sales receipt is already paid. |

*This document covers step 1 — the recurring estimate — and specifies precisely how it hands off to the posting transactions in step 3 (Section 12).*

## **1.2 Who this document is for**

* **Engineers** — for data model, APIs, scheduling and numbering logic, the non-posting/conversion behavior, and integration points.

* **Product & design** — for goals, user stories, flows, and screen behavior.

* **QA** — for acceptance criteria, edge cases, and the end-to-end test checklist.

* **Accounting reviewers** — for the non-posting rationale, the estimate status lifecycle, and the downstream journal entries in Section 12\.

## **1.3 How to read it**

Sections 1–8 give the product context (goals, personas, stories). Sections 9–11 specify behavior (screens, flows, scheduling, discount/tax, and status). Section 12 is the accounting contract — why the estimate is non-posting, its lifecycle, and the journal entries that post when it is converted. Sections 13–15 are the technical build (data, APIs, integrations). Sections 16–23 cover quality, permissions, and operations.

# **2\. Glossary & Terminology**

Consistent language keeps the spec unambiguous. These terms are used precisely throughout the document.

| Term | Meaning in this document |
| :---- | :---- |
| Recurring estimate template | The saved definition of a repeating estimate: customer, line items, pricing, discount/tax, and schedule. The template is not itself an estimate; it produces them. |
| Estimate (quote) | A proposal sent to a customer showing the items, prices, discount, and tax they can expect to pay. Non-posting. |
| Generated estimate | An actual estimate transaction the system creates from a template on a given date. It is non-posting and starts life as a Draft or Sent quote. |
| Non-posting | A transaction that records information but writes no journal entry and has no effect on the general ledger, the P\&L, or the balance sheet. An estimate is non-posting. |
| Type | One of Scheduled, Reminder, or Unscheduled — controls whether the system creates the estimate automatically, only nudges, or waits to be used on demand. |
| Customer | The person/company the quote is for. Selected from the Customer master; the estimate is addressed and (optionally) emailed to them. |
| Status | The estimate's lifecycle state: Draft, Sent (Pending), Accepted, Declined, Expired, or Invoiced (Closed). |
| Convert to invoice | The act of turning an accepted estimate into a posting invoice (or sales receipt). This is where accounting happens. |
| Progress invoicing | Invoicing an estimate in stages — by percentage, selected lines, or custom amounts — over time as the work is delivered. |
| Discount | A reduction applied to the estimate subtotal, as a percentage or a fixed amount (before or after tax). |
| Sales tax | Output tax computed on the taxable lines and shipping; only posts when the estimate becomes an invoice. |
| Estimate Total | The quoted grand total (subtotal − discount \+ tax \+ shipping). A non-posting figure until converted. |
| Estimates / pipeline report | The report of outstanding quotes by status — the business's quoted but un-booked sales pipeline. |
| Generation Job | The scheduled background process that creates Scheduled estimates (and can email them) and raises reminders when due. |

# **3\. Feature Goals & Objectives**

The feature removes repetitive data entry for repeat quotes, gets estimates to customers promptly, and gives the business a clean record of what it has quoted — all without touching the ledger until a customer accepts and the estimate is invoiced.

## **3.1 Business goals**

* **Automate repeat quotes.** Set up a recurring proposal once; Balanzify creates (and can email) the estimate every period.

* **Get quotes to customers on time.** Timely, consistent estimates keep deals moving and reduce manual effort for repeat work.

* **Make the sales pipeline visible.** Open and accepted estimates show quoted value the business expects to bill — useful for forecasting — without overstating income.

* **Speed up invoicing.** An accepted estimate converts to an invoice in one click (or in stages via progress invoicing), so nothing is re-entered.

* **Reach feature parity.** Recurring estimates are expected in cloud accounting for repeat and retainer work; their absence pushes users to manual re-entry.

## **3.2 User goals**

* Automate a fixed, standing quote so the estimate is created and sent every period without effort.

* Get a nudge for a quote that recurs but whose amounts change, then review before creating the estimate.

* Keep a library of complex quotes that are sent irregularly, so they never have to be rebuilt.

* Email the estimate to the customer automatically, with Cc/Bcc, and let them accept or decline.

* Convert an accepted estimate into an invoice (or sales receipt) in one step — or invoice it in stages.

* See at a glance which quotes are pending, accepted, declined, expired, or invoiced.

## **3.3 Non-goals (explicitly out of scope for v1)**

Stating what we are not building keeps the release focused and shippable. Several of these appear again in Section 22 as future work.

* Posting any accounting from the estimate itself — an estimate is non-posting by design (Section 12).

* Full customer-portal e-acceptance/e-signature flows (surfaced as a concept; a Sent→Accepted status hook is provided, richer portal acceptance is future work).

* Automatic deposit/retainer invoices on acceptance (planned as a fast-follow).

* Scheduled progress-invoicing plans that auto-invoice an estimate over time (manual progress invoicing is in scope; automation is future work).

* Pause/Resume/Skip, CSV import/export, and multi-currency-specific FX per template (planned fast-follows).

## **3.4 Success metrics**

| Metric | Definition | Target (first 90 days) |
| :---- | :---- | :---- |
| Adoption | % of active companies (that use estimates) with ≥1 recurring estimate template | ≥ 18% |
| Template volume | Median templates per adopting company | ≥ 2 |
| Automation rate | % of recurring estimates created by the job vs. manually | ≥ 55% |
| Auto-send usage | % of adopters that auto-email generated estimates to customers | ≥ 45% |
| Win / conversion rate | % of generated estimates accepted and invoiced within 60 days | ≥ 40% |
| Generation reliability | % of due templates created on time by the job | ≥ 99.9% |
| Error rate | % of generated estimates deleted within 48h | \< 3% |

# **4\. Competitive Research & Market Analysis (R\&D)**

Before designing the feature, we studied how estimates — also called quotes — and recurring estimates in particular are handled across the leading cloud accounting platforms used by small and mid-sized businesses. The goal was to identify the mental model users already expect, the fields that genuinely matter for a customer-facing quote, the status lifecycle an estimate moves through, how estimates are emailed and accepted, how they convert to invoices (including in stages), and — critically — the accounting treatment mature products converge on. To keep this document vendor-neutral, competitors are referenced as Platform A, Platform B, and Platform C rather than by brand name.

## **4.1 Research method**

* Reviewed public help documentation, sales guides, API references, and community threads for estimates/quotes and recurring quotes across three leading platforms.

* Mapped every user-facing field on the estimate form: customer, email, online-payment options, delivery details, discount, sales tax, shipping, line items, and customer-facing messages.

* Traced the estimate status lifecycle (draft, sent/pending, accepted, declined, expired, invoiced) and how a quote is emailed, accepted (via portal/email), and converted to an invoice or sales order — including progress invoicing.

* Confirmed the accounting treatment — that an estimate is non-posting and that income, A/R, and sales tax are only affected when the estimate is converted — and studied discount and sales-tax computation.

## **4.2 What the market has in common**

Despite different naming (“estimate” vs “quote”), the platforms converge on the same core ideas. This convergence is the strongest signal for what Balanzify should adopt.

* **An estimate is non-posting.** Every platform treats an estimate/quote as a proposal to a customer that writes no journal entry. It affects nothing on the financial statements until it is converted into an invoice or sales receipt.

* **Template-driven, parent–child.** A reusable template produces many dated estimates; editing the template affects future children only, never those already created.

* **A behavior spectrum.** From automatic creation (and emailing), to a reminder to create/send, to a purely on-demand template — the same three types Balanzify adopts.

* **A status lifecycle.** Estimates move Draft → Sent/Pending → Accepted or Declined (or Expired), then Invoiced when converted; declined/expired estimates are kept for the record, not deleted.

* **Emailed to the customer, accepted by them.** The estimate is sent to the customer's email (with Cc/Bcc), and the customer can accept or decline — often via a portal or a public link — which updates the status.

* **Convert to an invoice — in full or in stages.** An accepted estimate becomes an invoice (or sales order/receipt) with one action, and can be invoiced progressively (a percentage, selected lines, or custom amounts) as work is delivered.

* **Full sales pricing.** Estimates carry itemized lines, a discount (percentage or amount), sales tax (often automated by location), and shipping — all for display, none of it posting until conversion.

## **4.3 Where platforms differ**

| Dimension | Observed variation across platforms |
| :---- | :---- |
| Naming | Some call it “estimate”, others “quote”; a few expose both. Balanzify uses “Estimate” consistently. |
| Status granularity | Some use Pending/Accepted/Declined/Converted; others add Draft, Sent, and Expired. Balanzify adopts the fuller lifecycle (Section 7.3). |
| Acceptance channel | Customer acceptance may be via a portal, a public link, email, or manual marking. Balanzify supports manual status updates in v1 and reserves portal e-acceptance for a fast-follow. |
| Convert targets | An estimate may convert to an invoice, a sales order, or a sales receipt. Balanzify supports invoice and sales receipt in v1, matching its existing posting modules. |
| Progress invoicing | Support for invoicing an estimate in stages varies. Balanzify supports manual progress invoicing (partial conversion); scheduled progress plans are future work. |
| Deposits / retainers | Some auto-create a deposit/retainer invoice on acceptance. Balanzify treats this as future work (Section 22). |
| **R\&D conclusion** Adopt the market-standard model: a template-driven, parent–child recurring estimate with the three-type spectrum, a customer and optional auto-email, full sales pricing (line items, discount, sales tax, shipping), a clear Draft→Sent→Accepted/Declined/Expired→Invoiced lifecycle, and — above all — non-posting behavior with a clean one-click conversion to an invoice or sales receipt (in full or in stages) where the accounting actually happens. Delivered through Balanzify's existing Estimate form so it feels native, and positioned to automate repeat and retainer quotes. |  |

# **5\. Scope, Assumptions & Dependencies**

## **5.1 In scope (v1)**

* A central Recurring Transactions list page that displays all recurring templates for the company (hosting estimates in this release, alongside invoices, bills, expenses, cheques, and purchase orders).

* A “New” flow that asks which transaction type to create (Estimate in this release) before opening the template form.

* A recurring estimate template form supporting all three types, with customer, email (Cc/Bcc), online-payment options, interval, start/end, billing/shipping/ship-from addresses, ship-via/shipping-date/tracking, store, line items (with service date and per-line tax), discount, sales tax, shipping, customer-facing messages, and one attachment.

* A background Generation Job that creates Scheduled estimates, optionally emails them to the customer, and raises reminders when due.

* A Reminders List page showing reminder-type items that are due for action.

* Emailing a generated or opened estimate to the customer (PDF), with Cc/Bcc.

* Row actions: Edit, Use, Duplicate, Delete; and on a generated estimate: Send, Update status (Accepted/Declined/Expired), Convert to invoice/sales receipt (full or progress), Close.

* The estimate status lifecycle and one-click conversion to a posting transaction, including progress invoicing (Section 12).

* An Estimates view showing quotes by status (pending, accepted, declined, expired, invoiced).

* Full integration with the existing Customer, Products & Services, Sales Tax, Invoice/Sales-Receipt, and Email/Send subsystems.

* Audit logging of template create/edit/delete, generation, send, status-change, and conversion events.

## **5.2 Out of scope (v1)**

* Any posting from the estimate itself (non-posting by design).

* Portal e-signature acceptance, auto deposit/retainer invoices, and scheduled progress-invoicing plans.

* Pause/Resume/Skip, CSV import/export, and multi-currency-specific FX per template.

## **5.3 Assumptions**

* The one-off Estimate screen, Customer master, Products & Services, Sales Tax engine, Chart of Accounts, and the Invoice/Sales-Receipt modules already exist and are the source of truth.

* The platform can email documents to customers (the existing send/email service) and, later, surface acceptance via a customer portal.

* Each company (tenant) has a configured time zone; all scheduling and “today” comparisons use it.

* A reliable background job runner (cron/queue/worker) is available to run generation at least daily.

* Users are already authenticated and scoped to a company; standard role-based permissions apply.

## **5.4 Dependencies**

| Depends on | Why |
| :---- | :---- |
| Customer master | Supplies the customer, default email, and billing/shipping addresses on the estimate. |
| Products & Services | Line items reference a product/service that maps to an income account (used only when the estimate is invoiced). |
| Sales Tax engine | Computes tax on taxable lines and shipping for display; posts only on the invoice. |
| Invoice / Sales Receipt modules | The posting transactions an estimate converts into; they carry the journal entry (A/R or bank, income, tax). |
| Chart of Accounts | Income, A/R, sales-tax-payable, and discount accounts used by the resulting invoice. |
| Email / Send service | Delivers the estimate PDF to the customer with Cc/Bcc. |
| Customer Portal | Lets customers view and (in a fast-follow) accept/decline the estimate. |
| Reports / Projects | Pipeline and win-rate reporting draw on estimate status; lines can be tagged to projects. |
| Background job runner | Executes the Generation Job on schedule. |
| Notification service | Delivers reminders, acceptance notifications, and exception alerts (Section 19). |

# **6\. User Personas**

Three personas represent the distinct ways people use recurring estimates. Each maps naturally to one of the three template types, and each appears again in the user stories and flows.

## **6.1 Priya — Owner of a design studio (retainer clients)**

* **Context:** Sends the same monthly retainer proposal to a long-standing client before starting each month's work.

* **Needs:** The estimate created and emailed automatically each month so the client can approve it and she can then invoice.

* **Maps to:** Scheduled — fixed quote, automatic, auto-emailed.

## **6.2 Marcus — Sales bookkeeper**

* **Context:** Quotes a repeat customer monthly, but the scope and amounts change each time.

* **Needs:** A reminder before the quote is due so he can adjust the lines, then create and send the estimate himself.

* **Maps to:** Reminder — recurring cadence, human sets the final quote.

## **6.3 Dana — Operations manager (project bids)**

* **Context:** Occasionally sends a detailed project bid built from a standard scope, tagged to the project.

* **Needs:** A ready-made template she can use on demand, then progress-invoice as milestones are delivered.

* **Maps to:** Unscheduled — no timetable, used when a bid is needed.

# **7\. Concept Model & Feature Overview**

This section gives the shared mental model before the detailed spec. Everything else in the document builds on these ideas.

## **7.1 Template, not a transaction**

A recurring estimate template is a definition, not an estimate. It stores the customer, line items, pricing, and schedule. Estimates are produced from it — automatically for Scheduled templates, or on demand for the others. Editing the template changes future estimates only; estimates already created are never rewritten.

## **7.2 The three types**

| Type | What the system does | Best for |
| :---- | :---- | :---- |
| **Scheduled** | Creates the estimate automatically on each due date (and can email it to the customer), optionally a few days in advance. | Standing quotes — a monthly retainer proposal. |
| **Reminder** | Creates nothing automatically; on the reminder date it places an item in the Reminders List for a human to review, create, and send. | Recurring quotes whose scope varies each time. |
| **Unscheduled** | Keeps the template on the shelf until used; no timetable, no reminders. | Irregular but repeatable bids — project quotes. |

A user can change a template's type at any time. Switching to Scheduled or Reminder reveals the interval and start/end fields; switching to Unscheduled hides them because an unscheduled template has no timetable.

## **7.3 The estimate status lifecycle**

An estimate moves through states as the customer responds and the work is invoiced. None of these transitions post to the ledger; conversion to an invoice/sales receipt is the only accounting event (Section 12).

| Status | Meaning |
| :---- | :---- |
| Draft | Created but not yet sent. Editable freely; not counted in sales/pipeline reports. |
| Sent (Pending) | Emailed to the customer and awaiting their decision. The state a generated estimate reaches once created/sent. |
| Accepted | The customer approved the quote (via portal/email or marked manually). Ready to invoice. |
| Declined | The customer rejected the quote. Kept for the record; can be reopened if they change their mind. |
| Expired | The quote's validity date passed without a decision. Kept for the record; can be reissued. |
| Invoiced (Closed) | Converted to an invoice/sales receipt — fully, or partially via progress invoicing (the remainder stays open). |

## **7.4 What makes an estimate different from an invoice or sales receipt**

Because Balanzify also offers invoices and sales receipts (and their recurring versions), it is worth stating the difference plainly — it drives the fields and (the absence of) accounting.

| Aspect | Estimate | Invoice | Sales Receipt |
| :---- | :---- | :---- | :---- |
| Posts to ledger? | **No** | Yes | Yes |
| Represents | A proposal | Money owed by customer | Money received |
| Debit side | — (none) | Accounts Receivable | Bank / Undeposited funds |
| Customer pays? | Not yet | Later (on terms) | At the point of sale |
| Becomes | An invoice / sales receipt | — | — |

*The purchase-side analog of an estimate is a purchase order: both are non-posting proposals that convert into a posting transaction (an estimate→invoice on the sales side; a purchase order→bill on the purchase side).*

## **7.5 Where the feature lives in Balanzify**

Recurring Transactions is a shared list that hosts multiple transaction types; this release adds Estimate alongside the sales and purchase transactions. Conceptually it sits at the front of the Sales domain. The entry points are:

* **Recurring Transactions list** — the home base for every template.

* **“Make recurring” on an existing estimate** — a shortcut that turns an estimate the user is already editing into a template (see Section 9.6).

* **Reminders List** — a focused view of reminder-type items that are due for action.

* **Estimates** — where generated estimates are tracked by status until accepted, invoiced, declined, or expired.

## **7.6 Template lifecycle**

| Stage | What happens |
| :---- | :---- |
| Created | The user saves a template. If it is Scheduled or Reminder, the engine computes its first Next Date from the start date and interval. |
| Active | The template is live. On each due date the Generation Job either creates an estimate (Scheduled, optionally emailing it) or raises a reminder (Reminder). Previous Date and Next Date advance after each run. Unscheduled templates are “active” only in that they can be used at any time. |
| Ended | The schedule reaches its end condition (last occurrence reached, or end date passed). No further estimates or reminders are produced. The template remains visible for reference and can be reactivated by editing its end condition. |
| Deleted | The user deletes the template. Future generation stops immediately. All estimates already created remain (with their status and any linked invoices), untouched. The template is soft-deleted so history and audit links survive. |

# **8\. User Stories & Acceptance Criteria**

Requirements are expressed as user stories grouped into epics. Each uses the standard “As a … I want … so that …” form and is followed by testable acceptance criteria (AC). QA should be able to write test cases directly from the AC. Story IDs (EST-xx) are stable references used elsewhere in the document.

## **Epic A — Viewing recurring transactions**

### **EST-01  See all recurring templates**

As a *user managing sales*, I want a single list of every recurring estimate template so that I can see everything that repeats in one place.

#### **Acceptance criteria**

* The list shows columns: Template Name, Type, Txn Type, Interval, Previous Date, Next Date, Customer, Amount, and an Action menu.

* Templates are sortable by Template Name, Next Date, Customer, and Amount.

* A “Filter by name” box narrows the list as the user types.

* When there are no templates, an empty state explains what recurring transactions are and offers a “New” action.

* Amounts display in the company's base currency with correct formatting.

### **EST-02  Find templates and track estimates by status**

As a *sales bookkeeper*, I want to filter templates and see quotes by status so that I can track my pipeline.

#### **Acceptance criteria**

* Name filter matches on partial, case-insensitive text; a type/txn filter narrows to Estimate or a template type.

* An Estimates view lists generated estimates with customer, amount, date, and status (Draft/Sent/Accepted/Declined/Expired/Invoiced).

* Pagination appears when a list exceeds one page; the current range is shown.

## **Epic B — Creating a recurring estimate template**

### **EST-03  Start a new template and choose the type**

As a *user*, I want to create a new recurring transaction and pick which type of transaction it is, so that I can build the right kind of template.

#### **Acceptance criteria**

* Selecting “New” opens a “Select Transaction Type” dialog with a dropdown that includes Estimate.

* Confirming opens the recurring estimate template form; cancelling returns to the list with no changes.

### **EST-04  Configure a Scheduled estimate**

As *Priya (owner)*, I want an estimate to be created automatically so that my monthly retainer quote goes out every period without me.

#### **Acceptance criteria**

* Choosing Type \= Scheduled reveals a “Create \_\_ days in advance” field.

* Interval, Start date, and End condition fields are shown and required.

* On save, the engine computes the first Next Date and the template becomes active.

* On each due date the estimate is created automatically, set to Sent (if emailed) or Draft, and linked to the template.

### **EST-05  Configure a Reminder estimate**

As *Marcus (bookkeeper)*, I want to be reminded before a quote is due so that I can adjust the lines and create the estimate myself.

#### **Acceptance criteria**

* Choosing Type \= Reminder reveals a “Remind \_\_ days before the transaction date” field.

* No estimate is ever created automatically for a Reminder template.

* On the reminder date, an item appears in the Reminders List and a notification is sent.

* From the reminder, the user can open, adjust the lines, create the estimate, and send it in one flow.

### **EST-06  Configure an Unscheduled estimate**

As *Dana (ops manager)*, I want to save a complex quote without a schedule so that I can reuse it whenever a bid is needed.

#### **Acceptance criteria**

* Choosing Type \= Unscheduled hides the interval and start/end fields and shows an explanatory note.

* The template saves with no Next Date and never creates an estimate on its own.

* The template can be turned into an estimate anytime via the Use action.

### **EST-07  Name the customer, email recipients, and payment options**

As a *user*, I want to record the customer, where to email the quote, and how they can pay, so that the right customer receives it and can act on it.

#### **Acceptance criteria**

* Customer is selected from the Customer master and may auto-fill the email and addresses; new customers can be added inline.

* Email accepts one or more addresses (comma-separated) with optional Cc/Bcc.

* Online-payment options (Cards / Bank transfer) can be pre-selected to carry onto the invoice the estimate becomes.

* No terms or due-date field is shown on the estimate — those belong to the invoice.

### **EST-08  Set delivery details (addresses, ship-via, dates, store)**

As a *user*, I want to capture billing/shipping details so that the quote and any resulting invoice are accurate.

#### **Acceptance criteria**

* Billing address and Shipping-to/Shipping-from addresses can be set; they default from the customer/company and are editable.

* Ship Via, Shipping date, and Tracking no. capture fulfilment details; an optional Store (location) can be set.

* These details carry onto the created estimate and onward to the invoice on conversion.

### **EST-09  Build the quote (line items, discount, tax, shipping, messages)**

As a *user*, I want the template to capture the same detail as a normal estimate so that generated estimates are complete and ready to send.

#### **Acceptance criteria**

* Line items support Service date, Product/Service, SKU, Description, Quantity, Rate, Amount, and a per-line Tax (taxable) flag; subtotal lines can be added.

* A Discount (percentage or amount) and Sales tax (a selected rate or automated by location) can be applied, plus Shipping and tax on shipping.

* A running Subtotal, Taxable subtotal, Tax, and Estimate Total are displayed and recompute as lines change.

* Customer-facing “Message on estimate” and “Message on statement” can be set; a single Attachment (≤ 20 MB) can be added.

* None of these amounts post; they are for the quote and for the invoice it becomes (Section 12).

## **Epic C — Acting on templates**

### **EST-10  Use a template now**

As *Dana*, I want to create an estimate from a template on demand so that I can send an irregular bid without rebuilding it.

#### **Acceptance criteria**

* Use opens a pre-filled estimate (editable) or creates it directly, depending on the type.

* For Unscheduled and Reminder templates, Use is the primary way an estimate is produced.

* The created estimate is linked to the template, takes an estimate number, and appears in the Estimates view.

### **EST-11  Email the estimate to the customer**

As *Priya*, I want the estimate sent to the customer so that they can review and accept it.

#### **Acceptance criteria**

* A created estimate can be emailed as a PDF to the customer's address(es), with Cc/Bcc; sending sets status to Sent.

* Scheduled templates can auto-send on creation; other types can be sent manually via a Send action.

* A send failure (invalid/missing email) is surfaced clearly and the estimate remains re-sendable.

### **EST-12  Duplicate a template**

As a *user*, I want to duplicate a template so that I can build a similar one without starting over.

#### **Acceptance criteria**

* Duplicate creates a copy pre-filled with all fields, named “Copy of …”.

* The copy is independent; editing it does not affect the original.

* The copy starts with no run history (empty Previous Date).

### **EST-13  Delete a template safely**

As a *user*, I want to delete a template so that it stops generating — without disturbing estimates already created.

#### **Acceptance criteria**

* Delete asks for confirmation and warns that future generation will stop.

* After delete, no further estimates/reminders are produced.

* Estimates already created remain with their status and any linked invoices, unchanged.

* The action is recorded in the audit log.

### **EST-14  Edit a template without corrupting history**

As a *user*, I want edits to apply going forward so that estimates already created are never silently changed.

#### **Acceptance criteria**

* Edit opens the template pre-filled with its current values.

* Saving recalculates Next Date if the interval or start date changed.

* Changes never alter estimates already created (or invoices made from them).

* If a referenced item, customer, or tax rate was changed elsewhere, the user is warned before saving.

## **Epic D — Status, conversion & non-posting**

### **EST-15  Keep the estimate non-posting; accept and convert it to an invoice**

As *an accountant*, I want the estimate to post nothing until it becomes an invoice/sales receipt so that my books reflect only real sales.

#### **Acceptance criteria**

* Creating, editing, sending, accepting, declining, expiring, or closing an estimate writes no journal entry and does not affect income, A/R, sales tax, or the P\&L.

* The status can be updated (Accepted / Declined / Expired), manually or via the customer's response, without posting.

* A one-click Convert (to invoice, or sales receipt) creates the posting transaction pre-filled from the estimate and links the two.

* On conversion to an invoice, the invoice posts Dr Accounts Receivable and Cr Income (and Cr Sales Tax Payable); a sales receipt debits the bank instead (Section 12). Progress invoicing posts only the invoiced portion.

### **EST-16  Track, invoice, decline, and expire estimates**

As a *sales bookkeeper*, I want estimates to move through their statuses and drop off the open list when handled so that I always know my pipeline.

#### **Acceptance criteria**

* An estimate is Sent when emailed; accepting it enables invoicing; converting it (fully) sets it Invoiced (Closed); partial conversion leaves it open with a remaining balance.

* An estimate can be declined or marked expired; neither posts or reverses any accounting (nothing was posted), and both are retained for reporting.

* Declined/expired estimates can be reopened/reissued if the customer changes their mind.

# **9\. Detailed Functional Specification**

This section specifies every screen in the feature: its layout, each field, the rules that govern it, and the states it can be in. Field tables use a consistent shape — Field, Control, Required, and Behavior/Rules — so engineers and QA can work directly from them. Screens are described in the order a user encounters them.

## **9.1 Recurring Transactions list**

The list is the home of the feature. It shows all recurring templates for the company and is where users go to review, create, and act on them. The screen has a header (title, a view switcher, and a New button), a toolbar (name filter and a Filter control), and the templates table.

### **9.1.1 Columns**

| Column | Source | Behavior |
| :---- | :---- | :---- |
| Template Name | template.name | Clickable; opens the template for editing. Sortable. Primary identifier. |
| Type | template.type | Scheduled / Reminder / Unscheduled. |
| Txn Type | template.txn\_type | Estimate for these templates. Reserved for other types. |
| Interval | derived from schedule | Human-readable summary, e.g., “Every Month on the 1st”. Blank for Unscheduled. |
| Previous Date | template.previous\_run\_date | Date of the last created estimate/reminder; blank until first run. |
| Next Date | template.next\_run\_date | Next due date; blank for Unscheduled and Ended templates. |
| Customer | customer.display\_name | The customer. Clickable to the customer record. Sortable. |
| Amount | template total | Estimate Total, in base currency. Right-aligned. Sortable. |
| Action | — | Row menu: Edit (default) plus Use, Duplicate, Delete. |

### **9.1.2 Toolbar & controls**

* **Filter by Name** — live, case-insensitive, partial-match text filter.

* **Filter** — opens filter options (transaction type, template type); the current filter label is shown beside it.

* **New** — opens the Select Transaction Type dialog (Section 9.2).

* **View switcher** — toggles between Recurring Transactions, the Reminders List, and Estimates (by status).

## **9.2 Select Transaction Type dialog**

Choosing New opens a small dialog that asks which kind of recurring transaction to create. This keeps the list generic while sending the user to the correct form.

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Transaction Type | Dropdown | Lists available types, including Estimate. Selecting it and confirming opens the recurring estimate template form. |
| Confirm | Button | Proceeds to the template form for the chosen type. |
| Cancel | Button | Closes the dialog; returns to the list unchanged. |

## **9.3 Recurring estimate template form**

This is the core screen. It mirrors the one-off Estimate form so generated estimates are identical to hand-created ones, with a recurring header on top. The form is grouped into: identity & type, customer & email & payments, schedule, delivery details, line items, totals (discount/tax/shipping), customer messages, and footer (attachment, actions).

### **9.3.1 Identity & type**

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Template name | Text | Required. Human label shown in the list. Must be unique within the company (case-insensitive). |
| Type | Dropdown | Required. Scheduled / Reminder / Unscheduled. Changing it shows/hides schedule fields (9.3.2). |

### **9.3.2 Type-specific behavior**

| Type | What the form shows and does |
| :---- | :---- |
| Scheduled | Shows “Create \_\_ days in advance”. Interval, Start date, and End are required. On each due date the estimate is created automatically (and, if enabled, emailed → status Sent), and linked to the template. |
| Reminder | Shows “Remind \_\_ days before the transaction date”. Interval, Start date, and End are required. Nothing is created automatically; a reminder item is raised on the reminder date. |
| Unscheduled | Hides interval and start/end and shows a short note that the template has no timetable and is used on demand. |
| **Days in advance** “Create N days in advance” lets a Scheduled estimate be created a few days before its quote date so it reaches the customer in time. N \= 0 creates on the date itself. The estimate's date (occurrence date) is what the schedule advances from, regardless of how many days early it is created. |  |

### **9.3.3 Customer, email & online payments**

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Customer | Searchable dropdown | Required. Selects the customer from the Customer master; auto-fills the email and addresses. New customers can be added inline. |
| Email | Text (multi) | One or more recipient addresses, comma-separated; defaults from the customer. Used when the estimate is emailed. |
| Cc / Bcc | Expandable fields | Optional additional recipients for the estimate email. |
| Online payments (Cards / Bank transfer) | Checkboxes | Optional. Pre-select the payment methods offered when this estimate becomes an invoice, so the customer can pay online. |
| **No terms or posting fields on an estimate** **An estimate carries no payment terms, no due date, and no bank/income posting.** It is a quote, not a charge. Terms, tax posting, income, and A/R all appear on the invoice (or sales receipt) the estimate is later converted into (Section 12). |  |  |

### **9.3.4 Schedule — interval, start & end**

The interval builder answers “how often” and “starting when”. It is shown for Scheduled and Reminder templates and hidden for Unscheduled.

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Interval (frequency) | Dropdown | Daily / Weekly / Monthly / Yearly. Drives which sub-selectors appear. |
| On day / weekday | Dropdown(s) | For Monthly: “on day” \+ a day-of-month (1st–31st, clamped to month end). For Weekly: weekday(s). For Yearly: month \+ day. |
| Every N | Number | The “of every N month(s)/week(s)…” multiplier (≥ 1). |
| Start date | Date picker | Required for scheduled/reminder. The first date considered. Estimates are not generated for dates before today at creation time. |
| End | Dropdown | None (runs forever) / By date / After N occurrences. Reveals a date or count field as needed. |

### **9.3.5 Delivery details**

| Field | Control | Behavior / Rules |
| :---- | :---- | :---- |
| Billing address | Multi-line text | The customer billing address; defaults from the customer, editable. |
| Shipping to | Multi-line text | Where goods/services are delivered; defaults from the customer. |
| Shipping from | Text | The origin address goods ship from; defaults from company settings. |
| Ship Via / Shipping date / Tracking no. | Text / date | Fulfilment details carried onto the estimate and the invoice. |
| Store | Dropdown | Optional location/branch dimension carried onto the created estimate for reporting. |

### **9.3.6 Line items**

Line items describe what is being quoted. Each references a product/service that maps to an income account (used only when the estimate is invoiced).

| Column | Behavior / Rules |
| :---- | :---- |
| \# | Row number; rows can be reordered or deleted. |
| Service date | Optional date the service is/was rendered for that line. |
| Product/Service | References Products & Services; maps to an income account and default tax on conversion. |
| SKU | The item's stock-keeping unit; defaults from the product/service. |
| Description | Defaults from the item; editable. |
| Qty / Rate | Quantity × Rate computes the line Amount. |
| Amount | Computed; contributes to the Subtotal. |
| Tax | Per-line taxable flag; taxable lines feed the Taxable subtotal and sales-tax calculation. |

* Add lines / Clear all lines manage the grid; Add subtotal inserts a subtotal line to group items.

### **9.3.7 Totals — discount, tax & shipping**

| Element | Behavior / Rules |
| :---- | :---- |
| Subtotal | Sum of all line amounts, before discount and tax. |
| Discount | A percentage or fixed amount reducing the subtotal; configurable as applied before or after tax. |
| Taxable subtotal | The portion of the subtotal (after discount, per configuration) that is subject to sales tax. |
| Sales tax | Computed from a selected tax rate or “automated based on location”; shown for display only (posts on the invoice). |
| Shipping / Tax on shipping | An optional shipping charge and its tax. |
| Total / Estimate Total | The quoted grand total (subtotal − discount \+ tax \+ shipping). A non-posting figure until conversion. |

### **9.3.8 Customer messages**

| Field | Behavior / Rules |
| :---- | :---- |
| Message displayed on estimate | Free text shown to the customer on the estimate document. |
| Message displayed on statement | Text used as the line description if the estimate is later converted and shown on a statement. |

### **9.3.9 Footer — attachment & actions**

| Element | Behavior / Rules |
| :---- | :---- |
| Attachments | A single file up to 20 MB may be attached to the template (e.g., a scope document). Oversize files are rejected with a clear message. |
| Save template | Validates the form, computes the first Next Date (scheduled/reminder), and saves the template as active. |
| Clear | Resets the form fields without leaving the screen. |
| Cancel | Discards changes and returns to the list; a confirmation appears if there are unsaved edits. |

## **9.4 Actions on templates and generated estimates**

Templates support the standard row actions; a generated estimate adds status and conversion actions.

| Action | Behavior |
| :---- | :---- |
| Edit (template) | Default row click. Opens the template pre-filled; saving applies to future estimates only (EST-14). |
| Use (template) | Produces an estimate now — pre-filled and editable, or created directly — depending on type. Links it to the template. |
| Duplicate (template) | Creates an independent “Copy of …” template with empty run history. |
| Delete (template) | Confirms, stops future generation, leaves created estimates untouched, and writes an audit entry. |
| Send (estimate) | Emails the estimate PDF to the customer (Cc/Bcc); sets status to Sent. Re-sendable. |
| Update status (estimate) | Sets Accepted / Declined / Expired (manually or from the customer's response). Non-posting. |
| Convert (estimate) | Creates a linked invoice (or sales receipt), in full or via progress invoicing — the posting step (Section 12). |
| Close (estimate) | Marks the estimate handled/closed. Non-posting. |

## **9.5 Reminders List**

A focused view of reminder-type items that are due. Reached from the view switcher. It exists so variable quotes are reviewed and created deliberately.

| Element | Behavior |
| :---- | :---- |
| Due items | Shows reminder items due now, with Template name, Customer, expected Amount, and estimate date. |
| Find & filter | Supports find-by-name and a transaction-type filter. |
| Create action | Each item offers “create the estimate”; the user can adjust the lines and send after creating. |
| Empty state | When nothing is due, a clear empty state is shown. |
| Resolution | Once the estimate is created, the reminder item is cleared and won't nudge again for that occurrence. |

## **9.6 “Make recurring” from an existing estimate**

A shortcut lets a user turn an estimate they already created into a recurring template, so they don't rebuild it.

* From an existing estimate, “Make recurring” opens the template form pre-filled from that estimate (customer, email, addresses, lines, discount/tax, messages).

* The user adds a template name, type, and — for scheduled/reminder — an interval and start/end, then saves.

* The original estimate is unchanged; the new template governs future occurrences only.

## **9.7 Estimates view (by status)**

A list of generated estimates grouped/filterable by status, so the pipeline is visible.

| Element | Behavior |
| :---- | :---- |
| Contents | Lists estimates with customer, amount, date, status, and source template (if any). |
| Filter & sort | By customer, date, status (Draft/Sent/Accepted/Declined/Expired/Invoiced), or template. |
| Actions | From a row: Send, Update status, Convert to invoice/sales receipt, or Close. |
| Expiry | Optionally highlights estimates past their validity date so they can be reissued or expired. |

# **10\. User Flows**

These flows trace the main journeys end to end, step by step. They complement the screen spec (Section 9\) and the scheduling and status rules (Section 11), and show clearly where the non-posting estimate hands off to a posting transaction (Section 12).

## **10.1 Create a Scheduled estimate (Priya — automatic, auto-email retainer)**

1. From the Recurring Transactions list, Priya clicks New and selects Estimate.

2. She names the template “Acme Retainer — Monthly” and sets Type \= Scheduled, Create 3 days in advance, with auto-email enabled.

3. She picks Customer \= “Acme Co” (email and address auto-fill) and sets Interval \= Monthly on the 1st, Start \= the 1st of next month, End \= None.

4. She adds a service line: “Monthly design retainer”, qty 1, rate $2,000, taxable per location, and saves. Balanzify computes Next Date \= the 1st of next month.

5. Three days before the 1st, the Generation Job creates the estimate (dated the 1st), emails the PDF to Acme, and sets status Sent.

6. Nothing posts to the ledger. The estimate appears in the Estimates view as Sent, awaiting Acme's acceptance.

## **10.2 Reminder estimate (Marcus — variable scope)**

1. Marcus creates a template “Maintenance Quote — Monthly” with Type \= Reminder, Remind 4 days before the quote date.

2. Customer \= “River Ltd”; Interval \= Monthly on the 2nd; line items with placeholder scope; saves. Nothing is created yet.

3. Four days before the 2nd, an item appears in the Reminders List and Marcus is notified.

4. He opens it, adjusts the lines to the actual scope, creates the estimate, and emails it to River Ltd.

5. The reminder clears; next month the cycle repeats.

## **10.3 Unscheduled project bid \+ progress invoicing (Dana)**

1. Dana saves an Unscheduled template “Fit-out Bid — standard scope” with lines tagged to a project.

2. When a bid is needed, she uses the template, adjusts amounts, creates the estimate, and sends it to the client.

3. The client accepts; Dana marks the estimate Accepted (or it updates from the portal).

4. As milestones are delivered, she converts the estimate to invoices in stages (progress invoicing) — each invoice posts only its portion; the estimate shows the invoiced-to-date and remaining balance (Section 12.7).

## **10.4 Automatic generation & emailing (the Job's path)**

1. At the daily run, the Job selects active Scheduled and Reminder templates whose Next Date (minus any days-in-advance) is today or earlier, in the company time zone.

2. For each Scheduled template it creates an estimate with the quote date, assigns the next estimate number, links it to the template, records an occurrence, and (if enabled) emails it to the customer and sets status Sent.

3. For each Reminder template it raises a reminder item instead of creating.

4. It advances Previous/Next Date, honoring month-end and end conditions, and emits run metrics. No accounting is posted at any point.

5. Any occurrence that cannot create (e.g., a deleted customer) is failed in isolation, logged, and alerted — the rest of the run proceeds (Section 11.6).

## **10.5 Accept → convert to invoice (the posting step)**

1. The customer accepts the quote (via the portal/email or Marcus marks it Accepted).

2. From the Estimates view, the user opens the estimate and chooses Convert → Invoice.

3. Balanzify creates an invoice pre-filled from the estimate (customer, lines, discount, tax, shipping) and links the two.

4. The user sets terms/due date and confirms; on save, the invoice posts: Dr Accounts Receivable, Cr Income, and Cr Sales Tax Payable (Section 12). The estimate is set Invoiced (Closed).

5. The invoice is paid later by the customer through the normal receive-payment flow.

## **10.6 Progress / partial invoicing**

1. For a large accepted estimate, the user converts a portion — a percentage, selected lines, or a custom amount.

2. The invoice posts for that portion only; the estimate shows invoiced-to-date and the remaining balance and stays open.

3. As more is delivered, further invoices are raised until the estimate is fully invoiced, then it closes.

## **10.7 Decline / expire / edit / delete**

1. If the customer declines, the user marks the estimate Declined; if the validity date passes, it is Expired. Neither posts anything; both are kept for the record.

2. Editing the template changes future estimates only; estimates already created are untouched.

3. Deleting the template stops future generation; created estimates remain.

# **11\. Business Rules & Scheduling Engine**

The scheduling engine decides when each estimate is due and is shared with the other recurring modules; estimate numbering (11.8), discount/tax computation (11.9), and status transitions (11.10) are specific to this module. This section states the rules precisely so behavior is deterministic and testable. All date math uses the company's configured time zone and calendar (date-only) semantics.

## **11.1 Frequency & next-date algorithm**

A schedule is frequency \+ an “every N” multiplier \+ a position (day-of-month or weekday). The next date is computed from the last occurrence (or the start date for the first run).

* **Daily:** next \= last \+ N days.

* **Weekly:** next \= the configured weekday(s) in the week that is N weeks after the last.

* **Monthly:** next \= the configured day-of-month in the month that is N months after the last, clamped to month end (11.2).

* **Yearly:** next \= the configured month \+ day in the year that is N years after the last, clamped for Feb 29\.

## **11.2 Month-end clamping**

| Rule If the configured day-of-month does not exist in a target month (e.g., the 31st in February), the occurrence falls back to the last valid day of that month. A template set to the 31st creates on Feb 28 (or 29 in a leap year), Apr 30, and so on. The configured day is preserved for months that do have it. |
| :---- |

## **11.3 Days-in-advance (Scheduled)**

A Scheduled template may create the estimate N days before its quote date so it reaches the customer in time. Formally: create\_on \= quote\_date − days\_in\_advance, and the created estimate carries quote\_date as its date. N \= 0 creates on the date itself.

## **11.4 Reminder lead time**

A Reminder template raises its item N days before the quote date: remind\_on \= quote\_date − remind\_days\_before. The reminder persists until the user creates the estimate or the occurrence is otherwise resolved. No estimate is created automatically.

## **11.5 Start & end conditions**

| Setting | Behavior |
| :---- | :---- |
| Start date | The first date considered. No occurrence is generated for a date before today at creation time. |
| End \= None | The template runs indefinitely until stopped or deleted. |
| End \= By date | The last occurrence is on or before the end date; nothing generates after it. |
| End \= After N occurrences | Generation stops once N estimates/reminders have been produced; a counter tracks progress. |

## **11.6 The Generation Job**

A background process runs at least daily and turns due templates into created estimates or reminders. Correctness must not depend on how often it runs.

### **11.6.1 Selection & timing**

* Runs at least once per day at the company's configured local time; may run more frequently.

* Selects active (not ended, not deleted) Scheduled and Reminder templates whose next occurrence (accounting for days-in-advance) is due today or earlier.

### **11.6.2 Idempotency & exactly-once**

| Exactly-once creation Each occurrence is keyed by a unique (template\_id, occurrence\_date) record. Before creating, the Job checks this key; if it already exists, the occurrence is skipped. This guarantees a given period can never create two estimates — or send two emails — even if the Job runs twice, overlaps, or retries after a crash. |
| :---- |

### **11.6.3 Auto-email & failure handling**

* If the template has auto-email enabled, the Job emails the created estimate to the customer and sets status Sent; the send result is recorded on the occurrence. A send failure leaves the estimate created and re-sendable, and is alerted.

* Missed occurrences after downtime are processed in chronological order, subject to a configurable catch-up cap that is explicit and logged.

* An occurrence that cannot create (deleted customer, deleted line item) is failed in isolation, recorded with a reason, and alerted — never dropped silently; healthy templates are unaffected. Per-run metrics (processed / skipped / failed / emailed / duration) are emitted (Section 20).

## **11.7 Editing rules (future-only)**

* Editing a template changes future occurrences only; estimates already created (and any invoices made from them) are never rewritten.

* Changing the interval or start date recomputes Next Date on save.

* If a shared customer, item, or tax rate referenced by the template was changed elsewhere, the user is warned before saving so the impact is clear.

## **11.8 Estimate-numbering rules**

* **Sequential numbers.** Each created estimate takes the next number in the company's estimate sequence; numbering is serialized so two estimates cannot claim the same number under concurrent creation.

* **Manual override.** A user creating an estimate on demand may override the number; duplicates are warned.

* **Failed occurrences.** A failed/skipped occurrence does not consume an estimate number.

* **Reference on conversion.** The estimate number is carried onto the linked invoice/sales receipt for traceability.

## **11.9 Discount & tax computation**

* **Discount.** A percentage discount applies to the subtotal; a fixed-amount discount subtracts directly. The company setting determines whether the discount is applied before or after tax.

* **Taxable subtotal.** Only lines flagged taxable (and, per configuration, after discount) contribute to the taxable subtotal.

* **Sales tax.** Computed from the selected rate or automated by the customer's location; tax on shipping is added if configured. All tax is display-only on the estimate and posts only on the invoice.

* **Estimate Total.** Subtotal − discount \+ tax \+ shipping. This is a quoted figure and never posts.

## **11.10 Status-transition & expiry rules**

| Transition | Rule |
| :---- | :---- |
| Draft → Sent | Set when the estimate is emailed (or marked sent). Sent estimates count toward the pipeline. |
| Sent → Accepted / Declined | Set by the customer's response (portal/email) or manually. Only Accepted (or Sent, per policy) estimates can be invoiced. |
| → Expired | Set automatically when a validity/expiry date passes without acceptance, or manually. |
| → Invoiced (Closed) | Set when fully converted; partial conversion leaves it open with a remaining balance. |
| Reopen | Declined/Expired estimates can be reopened/reissued; conversion linkage and audit history are retained. |

# **12\. Accounting: Non-Posting Behavior & Downstream Posting**

This section is the accounting contract for the feature. Its central message is simple: an estimate posts nothing. This section explains why, how the estimate is tracked without touching the ledger, what its status lifecycle does (still nothing, accounting-wise), and — importantly — the exact journal entries that post when the estimate is converted into an invoice or sales receipt. That conversion is the only accounting event in the whole flow.

## **12.1 Why an estimate is non-posting**

An estimate is a proposal — a quote of what work will cost. Under accrual accounting, revenue is recognized when it is earned (goods/services delivered) and a receivable exists when the customer is actually billed — not when the business merely offers a price. At estimate time none of that has happened: nothing delivered, nothing billed, no obligation by the customer. So there is nothing to post.

* **No journal entry.** Creating, editing, sending, accepting, declining, expiring, or closing an estimate writes no debit and no credit.

* **No financial-statement impact.** An estimate does not change the profit & loss, income, Accounts Receivable, sales-tax liability, or the balance sheet.

* **Tax/discount are display-only.** The estimate shows discount and sales tax so the customer sees the expected price, but those figures do not post; they post on the invoice the estimate becomes.

| The rule, stated plainly An estimate is a non-posting transaction. It records a proposal and produces a document for the customer. The general ledger is untouched until the estimate is converted into a posting transaction — an invoice, or a sales receipt — after the customer accepts. |
| :---- |

What an estimate produces, in accounting terms:

| Ledger effect of an estimate Create Estimate  →  (no journal entry) Send / Accept / Decline / Expire / Close Estimate  →  (no journal entry) Convert Estimate to Invoice/Sales Receipt  →  posts here (12.4–12.6) |
| :---- |

## **12.2 How an estimate is tracked without posting**

* **A non-posting record.** The estimate is stored as a transaction with a status, but it is excluded from the general ledger and from all financial statements.

* **Pipeline / quoted value.** Open and accepted estimates are surfaced in reports so the business can see quoted value it expects to bill — a sales-pipeline figure, not a ledger balance, that never appears on the P\&L or balance sheet.

* **Linkage.** When converted, the estimate links to the resulting invoice/sales receipt so the proposal and the posting are connected for reporting and win-rate analysis.

## **12.3 The status lifecycle posts nothing**

| Transition | Accounting effect |
| :---- | :---- |
| Created / Draft / Sent | None. |
| Accepted / Declined / Expired | None — a customer decision is not an accounting event. |
| Invoiced (partially) | None from the estimate itself; the posting comes from the invoice created at conversion (12.7). |
| Closed | None — and nothing to reverse, because nothing posted. |

## **12.4 Converting to an Invoice — the posting event**

When the customer accepts and the estimate is converted to an invoice, the invoice is the posting transaction. It debits Accounts Receivable for the total and credits income for the goods/services and sales-tax payable for the tax. Example: a $2,000 service with $160 sales tax (8%).

| Account (on the resulting invoice) | Debit | Credit |
| :---- | ----- | ----- |
| Accounts Receivable (Asset) | $2,160.00 |  |
| Service Income |  | $2,000.00 |
| Sales Tax Payable (Liability) |  | $160.00 |
| **Total** | **$2,160.00** | **$2,160.00** |

*The estimate itself still posts nothing; this entry belongs to the invoice. The invoice is settled later when the customer pays (Dr Bank, Cr Accounts Receivable). The estimate is set Invoiced (Closed) and linked to the invoice.*

## **12.5 Converting to a Sales Receipt (paid at once)**

If the customer pays immediately rather than being billed, the estimate is converted to a sales receipt, which debits the bank (or undeposited funds) instead of Accounts Receivable. Same $2,000 service \+ $160 tax, paid on the spot.

| Account (on the resulting sales receipt) | Debit | Credit |
| :---- | ----- | ----- |
| Bank / Undeposited Funds (Asset) | $2,160.00 |  |
| Service Income |  | $2,000.00 |
| Sales Tax Payable (Liability) |  | $160.00 |
| **Total** | **$2,160.00** | **$2,160.00** |

*There is no Accounts Receivable because payment is received at the point of sale. The full behavior of each target lives in its own module; the estimate simply hands off the customer and lines.*

## **12.6 Discount & sales tax on the resulting invoice**

Discount and tax shown on the estimate post on the invoice. A discount is recorded as a reduction of revenue (a contra-income line), and tax reduces to the taxable base after discount (per configuration). Example: $2,000 subtotal, 10% discount ($200), tax 8% on the discounted $1,800 ($144).

| Account (on the resulting invoice) | Debit | Credit |
| :---- | ----- | ----- |
| Accounts Receivable (Asset) | $1,944.00 |  |
| Sales Discounts (contra-income) | $200.00 |  |
| Service Income |  | $2,000.00 |
| Sales Tax Payable (Liability) |  | $144.00 |
| **Total** | **$2,144.00** | **$2,144.00** |

*Some companies instead net the discount into the income line (crediting Income $1,800). Either way, the estimate posted nothing; the treatment follows the company's discount and tax configuration, and shipping income/tax (if any) posts on the invoice too.*

## **12.7 Progress / partial invoicing**

* If only part of an accepted estimate is invoiced (a percentage, selected lines, or a custom amount), only that portion posts — on the invoice — debiting A/R and crediting income/tax for the invoiced amount.

* The estimate records invoiced-to-date and the remaining balance and stays open; subsequent invoices post the remaining portions as work is delivered.

* When the estimate is fully invoiced, it closes. The estimate itself never posts — each progress invoice does.

## **12.8 A note on deposits & deferred revenue**

If a business collects a deposit or invoices before delivering, that advance is a liability (deferred/unearned revenue) until the work is done — handled by the invoice/deposit and revenue-recognition logic, not by the estimate. The estimate remains a non-posting quote; any deposit-on-acceptance behavior is future work (Section 22\) and does not change the non-posting rule.

## **12.9 Declining, expiring & closing**

* Declining, expiring, or closing an estimate writes no journal entry; it only updates the estimate's status and removes it from the active pipeline.

* Deleting an estimate removes a non-posting record and affects nothing on the ledger; declining is preferred to keep the history.

* Deleting a template does not touch any created estimate or its linked invoice; those follow their own module's rules.

## **12.10 How recurring generation behaves**

* Every generated estimate is non-posting — generation never writes to the ledger, no matter how many estimates are created or emailed.

* Scheduled templates create (and optionally email) estimates automatically; Reminder and Unscheduled templates create them only when a human acts. In all cases the posting happens later, at conversion.

* Creation is exactly-once per occurrence (Section 11.6.2), so a period can never produce two estimates or two customer emails.

* Because nothing posts at generation, a failed occurrence leaves the ledger completely unaffected — there is never a half-posted state to clean up.

# **13\. Data Model**

The data model stores templates, their schedule, their lines, and the occurrences they produce. It is shared in shape with the other recurring modules; the estimate-specific fields are the customer and email recipients, online-payment options, delivery details, discount and sales-tax settings, shipping, and customer-facing messages. Because an estimate is non-posting, there is no terms, no due date, and no bank/income posting fields on the template. Field tables list name, type, nullability, and notes. All records are scoped by company\_id (tenant).

## **13.1 recurring\_template**

The template header — identity, type, customer, pricing, and delivery details.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Template identifier. |
| company\_id | UUID (FK) | No | Owning tenant; every query is scoped by it. |
| name | text | No | Template name; unique per company (case-insensitive). |
| txn\_type | enum | No | estimate for these templates. |
| type | enum | No | scheduled | reminder | unscheduled. |
| customer\_id | UUID (FK) | No | Customer the quote is for — required. |
| email\_to | text | Yes | Recipient address(es), comma-separated; defaults from the customer. |
| email\_cc / email\_bcc | text | Yes | Optional additional recipients for the estimate email. |
| auto\_email | boolean | No | If true, Scheduled estimates are emailed on creation (status Sent). |
| online\_pay\_cards / online\_pay\_bank | boolean | No | Online-payment options to carry to the invoice. |
| billing\_address / shipping\_to / shipping\_from | text | Yes | Addresses printed on the estimate; default from customer/company. |
| ship\_via / shipping\_date / tracking\_no | text / date | Yes | Fulfilment details. |
| store\_id | UUID (FK) | Yes | Optional location/branch dimension. |
| discount\_type | enum | Yes | percent | amount. |
| discount\_value | decimal(19,4) | Yes | The discount percentage or fixed amount. |
| discount\_before\_tax | boolean | No | Whether discount applies before tax. |
| tax\_automated | boolean | No | If true, tax is automated by customer location. |
| tax\_rate\_id | UUID (FK) | Yes | Selected tax rate when not automated. |
| shipping\_amount | decimal(19,4) | Yes | Optional shipping charge. |
| message\_on\_estimate / message\_on\_statement | text | Yes | Customer-facing messages. |
| attachment\_id | UUID (FK) | Yes | Single reference file on the template (≤ 20 MB). |
| create\_days\_in\_advance / remind\_days\_before | int | Yes | Scheduled / Reminder lead (0–90). |
| currency\_code | char(3) | No | Quote currency. |
| total\_amount | decimal(19,4) | No | Cached Estimate Total (non-posting); recomputed on save. |
| previous\_run\_date / next\_run\_date | date | Yes | Run state; next is null for Unscheduled/Ended. |
| occurrences\_generated | int | No | Counter for End \= After N. |
| created\_by / created\_at / updated\_at / deleted\_at | — | — | Author, audit timestamps, soft-delete marker. |
| **Contrast with the posting sales modules** The Invoice template carries terms\_id / due date and posts to A/R and income; the Sales Receipt posts to a bank/deposit account. The Estimate template carries none of those — no terms, no posting accounts — because an estimate posts nothing. It adds customer email, online-payment options, discount/tax display settings, and customer messages. Those posting details appear only on the invoice/sales receipt the estimate becomes. |  |  |  |

## **13.2 recurring\_schedule (fields / value object)**

Stored per template (columns or JSON). Null for Unscheduled templates.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| frequency | enum | Yes | daily | weekly | monthly | yearly. |
| interval\_count | int | No | “Every N” multiplier; ≥ 1\. |
| day\_mode / day\_of\_month / weekday / ordinal / month\_of\_year | mixed | Yes | Position selectors (month-end clamped). |
| start\_date | date | No\* | First date considered (\*required for scheduled/reminder). |
| end\_type | enum | No | none | by\_date | after\_count. |
| end\_date / end\_after\_occurrences | date / int | Yes | Required for the matching end\_type. |

## **13.3 recurring\_template\_line**

One row per line item (or subtotal line). Sales lines reference a product/service that maps to an income account; there is no posting until the estimate is invoiced.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Line identifier. |
| template\_id | UUID (FK) | No | Parent template. |
| is\_subtotal | boolean | No | True for a subtotal line (no item). |
| service\_date | date | Yes | Date the service is/was rendered. |
| product\_service\_id | UUID (FK) | Yes | Product/Service; maps to an income account \+ default tax on conversion. |
| sku | text | Yes | Item SKU; defaults from the product/service. |
| description | text | Yes | Line description shown to the customer. |
| quantity | decimal(19,4) | Yes | Quantity quoted. |
| rate | decimal(19,4) | Yes | Unit price. |
| amount | decimal(19,4) | No | Line amount; sums to subtotal. |
| is\_taxable | boolean | No | Whether the line is subject to sales tax. |
| project\_id | UUID (FK) | Yes | Optional project tag carried forward to the invoice. |
| sort\_order | int | No | Row order. |

## **13.4 recurring\_occurrence**

One row per due date the engine acts on. The unique key guarantees exactly-once creation; it also powers the Reminders List and tracks the created estimate and its email result.

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| id | UUID (PK) | No | Occurrence identifier. |
| template\_id | UUID (FK) | No | Parent template. |
| occurrence\_date | date | No | Quote date for this run. |
| status | enum | No | created | reminded | failed | skipped. |
| generated\_estimate\_id | UUID (FK) | Yes | The created estimate (when status \= created). |
| estimate\_number | text | Yes | The estimate number assigned at creation. |
| email\_status | enum | Yes | sent | failed | not\_sent. |
| resolved\_at | timestamptz | Yes | When a reminder was acted on / occurrence closed. |
| error | text | Yes | Failure reason (when status \= failed). |
| UNIQUE(template\_id, occurrence\_date) | constraint | — | Enforces exactly-once creation per period. |

## **13.5 The estimate record & its links**

| Field | Type | Null | Description |
| :---- | :---- | :---- | :---- |
| estimate\_number | text | No | Sequential estimate/quote number. |
| status | enum | No | draft | sent | accepted | declined | expired | invoiced. |
| expiry\_date | date | Yes | Validity date after which the estimate expires. |
| invoiced\_amount | decimal(19,4) | No | Amount invoiced to date (progress invoicing); 0 until first conversion. |
| source\_template\_id / source\_occurrence\_id | UUID (FK) | Yes | Links a generated estimate to its template and occurrence. |
| linked\_invoice\_id | UUID (FK) | Yes | The invoice/sales receipt this estimate was converted into. |
| linked\_transaction\_type | enum | Yes | invoice | sales\_receipt (when converted). |

*The estimate record is stored as a non-posting transaction — excluded from the general ledger and financial statements — until (and only through) the linked posting transaction created at conversion.*

## **13.6 Sample template (JSON)**

| recurring\_template (estimate) {   "id": "tmpl\_es4",   "txn\_type": "estimate",   "type": "scheduled",   "name": "Acme Retainer — Monthly",   "customer\_id": "cus\_acme",   "email\_to": "ap@acme.com",   "auto\_email": true,   "online\_pay\_cards": true, "online\_pay\_bank": true,   "discount\_type": null, "tax\_automated": true,   "shipping\_amount": 0,   "message\_on\_estimate": "Thank you for your business",   "create\_days\_in\_advance": 3,   "schedule": {     "frequency": "monthly", "interval\_count": 1,     "day\_mode": "day\_of\_month", "day\_of\_month": 1,     "start\_date": "2026-08-01", "end\_type": "none"   },   "lines": \[     { "product\_service\_id": "itm\_retainer", "description": "Monthly design retainer",       "quantity": 1, "rate": 2000.00, "amount": 2000.00, "is\_taxable": true }   \],   "total\_amount": 2160.00,   "next\_run\_date": "2026-08-01" } |
| :---- |

# **14\. API Specification**

The feature exposes a small, REST-style API. All endpoints are tenant-scoped and permission-checked server-side (Section 17). Requests and responses are JSON; money is decimal in base currency; dates are calendar dates. Only representative endpoints and payloads are shown.

## **14.1 Endpoint summary**

| Method & path | Purpose | Notes |
| :---- | :---- | :---- |
| GET /api/v1/recurring-templates | List templates | Supports q (name), type, txn\_type, sort, pagination. |
| POST /api/v1/recurring-templates | Create a template | Validates schedule, customer, email, lines, discount/tax; computes next\_run\_date. |
| GET /api/v1/recurring-templates/{id} | Fetch one | Full template with schedule and lines. |
| PUT /api/v1/recurring-templates/{id} | Edit a template | Future-only; recomputes next\_run\_date if schedule changed. |
| DELETE /api/v1/recurring-templates/{id} | Delete a template | Stops future generation; created estimates untouched. |
| POST /api/v1/recurring-templates/{id}:use | Use now | Creates an estimate from the template. |
| GET /api/v1/recurring-reminders | List due reminders | Powers the Reminders List. |
| POST /api/v1/estimates/{id}:send | Email an estimate | Sends the PDF to the customer; sets status Sent. |
| POST /api/v1/estimates/{id}:status | Update status | Accepted / Declined / Expired (non-posting). |
| POST /api/v1/estimates/{id}:convert | Convert an estimate | Creates a linked invoice/sales receipt (the posting step); supports partial. |
| GET /api/v1/estimates?status=sent | List estimates by status | Powers the Estimates / pipeline view. |

## **14.2 Create template**

| Request / responses POST /api/v1/recurring-templates {   "name": "Maintenance Quote — Monthly",   "txn\_type": "estimate",   "type": "reminder",   "customer\_id": "cus\_river",   "email\_to": "buyer@river.com",   "auto\_email": false,   "tax\_automated": true,   "remind\_days\_before": 4,   "schedule": { "frequency": "monthly", "interval\_count": 1,                  "day\_mode": "day\_of\_month", "day\_of\_month": 2,                  "start\_date": "2026-08-02", "end\_type": "none" },   "lines": \[ { "product\_service\_id": "itm\_maint", "description": "Maintenance",                "quantity": 1, "rate": 0, "amount": 0, "is\_taxable": true } \] } 201 Created  → full template with server-computed next\_run\_date. 422  → e.g. { "errors": \[ { "field": "customer\_id", "code": "required" },                         { "field": "email\_to", "code": "invalid\_email" } \] } |
| :---- |

## **14.3 Send, update status & convert**

| Send / status / convert API POST /api/v1/estimates/{id}:send { "to": \["buyer@customer.com"\], "cc": \[\], "bcc": \[\] } → emails the estimate PDF; sets status Sent. POST /api/v1/estimates/{id}:status   { "status": "accepted" } → updates status (non-posting). POST /api/v1/estimates/{id}:convert { "target": "invoice",            // invoice | sales\_receipt   "mode": "partial",              // full | partial   "percent": 50                   // or lines\[\]/amount for progress } → creates a linked, pre-filled invoice (the posting transaction),   sets the estimate Invoiced (or leaves it open with a balance),   and returns the new invoice id. The estimate itself posts nothing. |
| :---- |

## **14.4 List estimates by status**

| Estimates by status GET /api/v1/estimates?status=sent\&sort=date 200 OK { "data": \[    { "id": "est\_1", "estimate\_number": "EST-1042", "customer": "Acme Co",      "date": "2026-08-01", "amount": 2160.00, "status": "sent",      "invoiced\_amount": 0, "source\_template\_id": "tmpl\_es4",      "linked\_invoice\_id": null } \],   "page": 1, "page\_size": 25, "total": 1 } |
| :---- |

## **14.5 Error model**

* Validation errors return 422 with a list of { field, code } (e.g., customer required, invalid\_email, at\_least\_one\_line, discount\_out\_of\_range).

* Convert returns 409 if the estimate is fully invoiced/closed or not in an invoiceable status; permission failures return 403; missing records return 404\.

* Creation is idempotent server-side: a repeated create for the same occurrence returns the existing estimate rather than creating a duplicate or sending a second email.

# **15\. Integration with Other Modules**

The feature is not standalone — it reuses and connects to existing parts of Balanzify. This section lists every connection and what flows across it, so engineers know what they touch and QA knows what to regression-test. Note that, because an estimate is non-posting, the ledger-facing integrations are exercised only at conversion.

| Module | How the feature connects to it |
| :---- | :---- |
| Customer master | Supplies the customer, default email, and billing/shipping addresses; generated estimates reference the customer for reporting and pipeline. |
| Products & Services | Line items reference a product/service that maps to an income account and default tax; used only when the estimate is invoiced. |
| Sales Tax engine | Computes tax on taxable lines and shipping (selected rate or automated by location) for display; the tax posts to Sales Tax Payable only on the invoice. |
| Invoice / Sales Receipt modules | The posting transactions an estimate converts into; they carry the journal entry (A/R or bank, income, tax, discount). The estimate links to the created transaction. |
| Chart of Accounts | Income, Accounts Receivable, Sales Tax Payable, and Sales Discounts accounts used by the resulting invoice/sales receipt. |
| Email / Send service | Delivers the estimate PDF to the customer with Cc/Bcc; records send status and sets the estimate to Sent. |
| Customer Portal | Lets customers view and (in a fast-follow) accept or decline the estimate, updating its status. |
| Reports / Projects | Pipeline, quoted value, and win-rate reporting draw on estimate status; lines can be tagged to projects, and converted estimates appear via their linked invoice in sales/A/R reports. |
| Audit log | Template create/edit/delete, generation, send, status-change, convert, and close are logged with actor (or “system”), timestamp, and before/after. |
| Notifications | Reminders, send/acceptance notifications, and exception alerts are delivered through the existing notification service (Section 19). |
| Background job runner | Executes the Generation Job on the company's schedule (Section 11.6). |

# **16\. Edge Cases, Validation & Error Handling**

This section lists the validation the form enforces, the behavioral edge cases the engine must handle, and the principles for surfacing errors.

## **16.1 Validation rules (form & API)**

| Rule | Behavior |
| :---- | :---- |
| Template name required & unique | Non-empty; unique per company (case-insensitive). |
| Customer required | An estimate must name the customer it is for. |
| Email format | Each recipient (To/Cc/Bcc) must be a valid address; multiple are comma-separated. Required only if auto-email/send is used. |
| Type-conditional schedule | Scheduled/Reminder require interval \+ start \+ end; Unscheduled forbids them. |
| Days-in-advance / remind-before range | Integer 0–90; shown only for the relevant type. |
| At least one line | A template must have at least one line item (subtotal lines don't count). |
| Amounts / quantities | Non-negative; line amount \= quantity × rate; totals recompute automatically. |
| Discount range | A percentage discount is 0–100; a fixed discount cannot exceed the subtotal. |
| Tax configuration | Either automated-by-location or a selected tax rate; taxable lines drive the taxable subtotal. |
| No terms/posting on the estimate | Terms, due date, income, A/R, and tax posting are not captured on the estimate; they apply on the invoice. |
| End settings | end\_type \= by\_date needs a date; after\_count needs N ≥ 1\. |
| Attachment size | ≤ 20 MB; larger files rejected with a clear message. |
| Start not in the past (at creation) | Occurrences are not generated for dates before today when the template is created. |

## **16.2 Behavioral edge cases**

| Situation | Expected behavior |
| :---- | :---- |
| Day-of-month \> days in month | Clamp to the last day of that month (e.g., 31st → Feb 28/29). |
| Customer deleted/inactive | Block or warn on save; at generation the occurrence fails in isolation and is alerted — no estimate is created and nothing posts (nothing ever does). |
| Line item / tax rate deleted | Warn on edit; failed occurrences surface for correction rather than creating an estimate referencing a missing item/rate. |
| Email send fails | The estimate is still created; the failure is recorded and alerted, and the estimate can be re-sent. |
| Convert an already-invoiced/closed estimate | Blocked (409) unless progress invoicing leaves a remaining balance; a fully invoiced estimate cannot be converted again. |
| Progress / partial invoicing | Only the invoiced portion posts; the estimate tracks invoiced-to-date and remaining balance and stays open until fully invoiced. |
| Customer declines then changes mind | A Declined/Expired estimate can be reopened/reissued; its history and links are retained. |
| Accept without invoicing | An Accepted estimate still posts nothing; posting occurs only when it is converted. |
| Non-posting confirmation | Creating/editing/sending/accepting/declining/expiring/closing an estimate must produce no ledger entry — verified in tests (Section 21). |
| Job downtime / catch-up | Missed occurrences are caught up in order (subject to the cap); no duplicate estimates or emails (unique occurrence key). |
| Duplicate run / overlap | Exactly-once key prevents a second estimate and a second email for the same occurrence date. |
| Time-zone / DST boundary | Quote-date math uses the company time zone and date-only semantics, so an estimate dated the 1st is the 1st regardless of worker location. |
| Editing mid-cycle | Applies to future occurrences only; estimates already created (and invoices made from them) are unchanged. |

## **16.3 Error-handling principles**

* Fail one occurrence, not the run: a single bad occurrence never blocks healthy templates.

* Creation and posting are separate: generation never posts, so a generation failure never leaves a half-posted ledger; a conversion failure never leaves a half-created estimate.

* Prefer skip-and-alert over guess: when unsure (deleted customer/item), fail the occurrence with a clear reason rather than creating a broken estimate.

* Every failure is visible: failures (including email sends) are logged, alerted, and retriable — never silent.

# **17\. Permissions & Roles**

Access follows the platform's existing role model and is enforced server-side on every endpoint; the UI hides or disables actions the current role cannot perform. Creating and sending estimates is broadly available (an estimate commits nothing financially), but converting an estimate — which creates a posting invoice/sales receipt — requires the permission to create that posting transaction.

| Capability | Admin | Accountant | Bookkeeper | Sales | Viewer |
| :---- | :---- | :---- | :---- | :---- | :---- |
| View templates, reminders & estimates | ✔ | ✔ | ✔ | ✔ | ✔ |
| Create / edit templates | ✔ | ✔ | ✔ | ✔ | — |
| Delete templates | ✔ | ✔ | ✔ | — | — |
| Create / use an estimate | ✔ | ✔ | ✔ | ✔ | — |
| Send estimate & update status | ✔ | ✔ | ✔ | ✔ | — |
| Convert estimate → invoice / sales receipt | ✔ | ✔ | ✔ | ○\* | — |
| Close / decline / expire an estimate | ✔ | ✔ | ✔ | ✔ | — |

○\* Converting an estimate creates a posting transaction, so it requires the permission to create that invoice/sales receipt; a Sales user who lacks it can create, send, and update the status of estimates but not convert them. All endpoints enforce these permissions server-side.

# **18\. Non-Functional Requirements**

Because recurring estimates run unattended and email customers, the module is held to explicit bars for performance, reliability, numbering integrity, security, and correctness across time zones. Each requirement is written so QA can turn it into a measurable test.

## **18.1 Performance**

| Area | Requirement | Target |
| :---- | :---- | :---- |
| List page load | Recurring Transactions list renders the first page | ≤ 1.5 s (p95) for ≤ 500 templates |
| Template save | Create/update a template and recompute Next Date | ≤ 800 ms (p95) |
| Reminders / Estimates load | Query and render due reminders or estimates by status | ≤ 1.5 s (p95) |
| Use / create one estimate | Materialize an estimate and assign a number | ≤ 1 s (p95) |
| Send estimate email | Queue and dispatch the estimate PDF to the customer | ≤ 2 s (p95) to enqueue |
| Convert to invoice | Create the linked, pre-filled invoice | ≤ 1.5 s (p95) |
| Generation throughput | Estimates created per minute per worker | ≥ 2,000 occurrences/min |
| Job window | Full daily sweep for a large tenant | ≤ 10 min for 50k active templates |

## **18.2 Scalability & multi-tenancy**

* **Tenant isolation.** Every query, job selection, and API response is scoped by company\_id; no cross-tenant read or write is possible, enforced in the data-access layer.

* **Horizontal scale.** The Generation Job is shardable by company\_id so multiple workers run in parallel without contention.

* **Serialized numbering.** Estimate-number assignment is serialized per company so parallel workers never claim the same number, without a global lock.

* **Async email.** Customer emails are enqueued and sent asynchronously so a slow mail provider never blocks estimate creation or the job.

## **18.3 Reliability & correctness**

* **Generation reliability ≥ 99.9%.** Of all templates due on a day, at least 99.9% create on time; the rest catch up on the next run.

* **Exactly-once creation.** The unique (template\_id, occurrence\_date) key guarantees a period can never create two estimates or send two emails.

* **No accidental posting.** Generating, editing, sending, accepting, declining, expiring, or closing an estimate never writes to the general ledger — asserted in automated tests.

* **Numbering integrity.** Every created estimate has a valid, non-duplicate number; failed occurrences consume none.

* **No silent loss.** A failed occurrence or email is recorded, alerted, and retriable; it is never dropped.

## **18.4 Security & privacy**

* **Authorization on every call.** Server-side permission checks (Section 17\) gate every template, estimate, send, status, and convert action; conversion requires the posting-transaction permission.

* **Customer-data protection.** Customer emails and addresses are access-controlled to the owning company; estimate emails are sent only to configured recipients, and portal links are scoped and expiring.

* **Attachment safety.** Template attachments (≤ 20 MB) are virus-scanned, access-controlled, and served via signed, expiring URLs; emailed PDFs are generated server-side.

* **Encryption.** All traffic is TLS; records and attachments are encrypted at rest per platform standards.

* **Least-privilege job.** The worker runs with a scoped identity able to create estimates, assign numbers, send email, and write occurrences/audit — nothing more, and it cannot post to the ledger.

## **18.5 Time zones, dates & i18n**

* **Company-local scheduling.** All due-date math, days-in-advance, reminder offsets, and “today” comparisons use the company time zone.

* **Date-only quote dates.** Quote dates are calendar dates, so an estimate created early still bears its intended date regardless of worker location.

* **Locale & translation.** Amounts/dates and the estimate document render in the company/customer locale; all labels and email templates are externalized for localization.

## **18.6 Availability & observability**

* Interactive endpoints target the platform's standard availability SLO; a job outage delays creation but never loses it (catch-up guarantees eventual completion).

* The job emits structured metrics (processed / skipped / failed / emailed / duration) and logs per run, with alerting when failures or run duration cross a threshold.

* A dead-letter path captures occurrences that fail repeatedly so on-call can remediate without blocking healthy templates.

# **19\. Notifications**

Notifications keep users informed without pulling them into the app, and distinguish reminders that need a decision from confirmations that automation ran and quotes went out — and from customer responses. They respect the user's global preferences.

## **19.1 Reminder notifications (Reminder templates)**

* **Trigger.** On a Reminder template's computed reminder date (quote date minus “remind N days before”).

* **Content.** Template name, customer, expected amount, quote date, and a direct link to review, create, and send the estimate.

* **Grouping.** Multiple reminders due the same day may be rolled into one digest; each still links to its item.

* **Lifecycle.** Once the estimate is created, the reminder clears and no further nudges are sent for that occurrence.

## **19.2 Send confirmations & customer responses**

* **Send confirmation.** When a Scheduled estimate is auto-emailed, an optional confirmation records that the customer was sent the quote.

* **Accepted / Declined.** When a customer accepts or declines (via portal/email or a manual update), the owner is notified so they can invoice or follow up.

* An optional periodic digest lists estimates the engine created: customer, amount, estimate number, send status, and a link to each.

## **19.3 Failure & exception alerts**

| Exceptions always surface Even with summaries disabled, a failed creation (deleted customer, deleted line item) or a failed email send raises an alert to an authorized user with the reason and a link to the template/estimate. A customer silently not receiving a quote, or a quote silently not being created, is never acceptable. |
| :---- |

## **19.4 Expiry & channels**

| Channel / type | Used for | Default |
| :---- | :---- | :---- |
| In-app / bell | Reminders, send/acceptance updates, exceptions | On |
| Email | Reminders and exception alerts; optional summaries | On for reminders/exceptions |
| Digest roll-up | Multiple same-day reminders or created-estimate lists | On (grouped) |
| Expiring-estimate nudge | Estimates approaching their validity date without a decision | Off (opt-in) |

* Recipients follow role and per-template responsibility; users who can act on the template receive its reminders/exceptions.

* All types honor the user's global preferences; transactional exception alerts may be non-optional by policy.

# **20\. Analytics & Reporting**

Two audiences consume data from this module: end users, who need to see and manage recurring quotes and their pipeline, and the product/engineering team, who need to know whether the feature delivers value and runs reliably — all without exposing one tenant's data to another.

## **20.1 User-facing reports**

* Recurring Templates report: grouped by Type, with Template Name, Customer, Interval, Previous/Next Date, Amount, and Status; totals per group.

* Estimates by status: quotes grouped as Draft/Sent/Accepted/Declined/Expired/Invoiced, with quoted value per group — the sales pipeline (a memo view, not a ledger balance).

* Win / conversion rate: how many estimates are accepted and invoiced, and how quickly; and expiring estimates that need attention.

* Invoiced-to-date vs remaining: for progress-invoiced estimates, how much has been billed vs. remains.

| Cross-module reporting An estimate posts nothing, so it never appears on the P\&L or balance sheet. Once converted, the resulting invoice/sales receipt flows into sales, A/R, and tax reports normally, and the estimate→invoice link lets reports trace booked revenue back to the quote it came from (and compute win rate). |
| :---- |

## **20.2 Product instrumentation & success metrics**

These events feed the success metrics in Section 3.4 (adoption, automation rate, auto-send usage, win/conversion rate, generation reliability, error rate). They are aggregated for analytics and contain no sensitive detail beyond what analytics requires.

| Event | Fires when | Key properties |
| :---- | :---- | :---- |
| template\_created | A template is saved | type, interval, auto\_email, line\_count, has\_discount |
| template\_edited / template\_deleted | A template changes/removed | changed\_fields / age\_days, occurrences\_generated |
| estimate\_generated | The job creates a Scheduled estimate | template\_id, occurrence\_date, amount, emailed, latency |
| estimate\_sent | An estimate is emailed to the customer | recipients\_count, result |
| estimate\_status\_changed | Accepted / Declined / Expired set | from, to, source (portal/manual) |
| estimate\_converted | An estimate is converted | target (invoice/sales\_receipt), partial, days\_open |
| reminder\_raised / reminder\_actioned | A reminder becomes due / is created | template\_id, time\_to\_action |
| job\_run | A generation sweep completes | processed, skipped, failed, emailed, duration\_ms |

## **20.3 Operational dashboards**

* Reliability: on-time creation rate, job duration, failed/dead-lettered occurrences, and email-send success — against the 99.9% bar.

* Adoption & automation: companies with ≥ 1 template, templates per company, auto-send usage, and the share of estimates created by the job vs. manually.

* Win & pipeline: estimate→invoice conversion (win) rate and time-to-convert; total open quoted value and expiring quotes.

* Health: estimates deleted within 48 hours of creation (the error-rate guardrail), watched for regressions after releases.

# **21\. QA & Acceptance Checklist**

This checklist turns the acceptance criteria (Section 8), scheduling and status rules (Section 11), the non-posting/conversion accounting (Section 12), and edge cases (Section 16\) into concrete, testable items. Every box must be verifiable before the module ships.

## **21.1 List, create & schedule**

| \# | Test |
| ----- | :---- |
| 1 | List shows Template Name, Type, Txn Type, Interval, Previous Date, Next Date, Customer, Amount, and Action; sorting and name-filter work. |
| 2 | “New” opens Select Transaction Type; Estimate opens the template form; Cancel returns unchanged. |
| 3 | Scheduled shows “Create \_\_ days in advance”; interval/start/end required; first Next Date computed correctly. |
| 4 | Reminder shows “Remind \_\_ days before”; nothing is created automatically; item appears on the reminder date. |
| 5 | Unscheduled hides schedule fields and never creates an estimate on its own. |
| 6 | Daily / weekly / monthly / yearly and “every N” each produce the correct Next Date; month-end clamps (31st → Feb 28/29). |
| 7 | End conditions None / By date / After N each stop generation at the right point. |

## **21.2 Customer, email, lines, discount & tax**

| \# | Test |
| ----- | :---- |
| 8 | Customer is required; selecting it auto-fills email and addresses; new customer can be added inline. |
| 9 | Email accepts multiple comma-separated recipients with Cc/Bcc; invalid addresses are rejected; online-payment options save. |
| 10 | No terms or due-date field appears on the estimate. |
| 11 | Line items add/remove; Service date, SKU, Qty×Rate=Amount, and per-line Tax flag work; Add subtotal inserts a subtotal line. |
| 12 | Discount (percent/amount, before/after tax) computes correctly; taxable subtotal reflects taxable lines and discount. |
| 13 | Sales tax (selected rate or automated by location) and tax-on-shipping compute; Estimate Total \= subtotal − discount \+ tax \+ shipping. |
| 14 | Messages on estimate/statement and a single attachment (≤ 20 MB) save; oversize files are rejected clearly. |

## **21.3 Non-posting behavior & conversion (Section 12\)**

| \# | Test |
| ----- | :---- |
| 15 | Creating an estimate writes no journal entry and does not change income, A/R, sales tax, or the P\&L. |
| 16 | Sending, accepting, declining, expiring, or closing an estimate also writes no journal entry. |
| 17 | Converting an estimate to an invoice creates a linked invoice that posts Dr Accounts Receivable, Cr Income, and Cr Sales Tax Payable; the estimate posts nothing. |
| 18 | Converting to a sales receipt debits the bank/undeposited funds instead of A/R; the estimate posts nothing. |
| 19 | A discount posts as a contra-income (or net income) on the invoice per configuration; tax posts to Sales Tax Payable on the discounted base. |
| 20 | Tax and discount shown on the estimate are display-only and post only on the invoice/sales receipt. |
| 21 | Progress/partial invoicing posts only the invoiced portion; the estimate tracks invoiced-to-date and remaining balance and stays open. |
| 22 | A fully invoiced/closed estimate cannot be converted again (409); the estimate→invoice link is retained for audit and win-rate. |

## **21.4 Generation, actions & integrity**

| \# | Test |
| ----- | :---- |
| 23 | “Create N days in advance” creates the estimate N days early but dates it on its quote date. |
| 24 | Auto-email sends the estimate to the customer on creation and sets status Sent; a send failure leaves it re-sendable and is alerted. |
| 25 | Running the job twice for the same day never creates a duplicate estimate or a second email (unique occurrence key holds). |
| 26 | A delayed job catches up missed occurrences (subject to the cap) without duplicating. |
| 27 | All date math uses the company time zone; an estimate dated the 1st is the 1st regardless of worker location. |
| 28 | Each created estimate takes the next estimate number; a failed occurrence consumes none; duplicates are warned. |
| 29 | Use creates a linked estimate and (for Scheduled) advances Previous/Next Date; status updates (Accepted/Declined/Expired) work and post nothing. |
| 30 | Duplicate creates an independent “Copy of …” with empty run history; editing it never affects the original. |
| 31 | Delete stops future generation, leaves created estimates and any linked invoices untouched, and writes an audit entry. |
| 32 | Editing a template never rewrites created estimates or invoices made from them; only future occurrences change. |
| 33 | Permissions are enforced server-side; converting an estimate requires the posting-transaction permission; all actions are audited. |
| **Definition of done** All 33 checks pass across the three template types; an estimate never posts to the ledger on any status change; conversion produces a correctly posted, linked invoice/sales receipt (with discount and tax handled correctly); progress invoicing posts only its portion; estimate numbering is clean; performance targets in 18.1 are met at p95; and no cross-tenant access is possible in any list, API, generation, email, or convert path. |  |

# **22\. Future Enhancements**

The v1 scope is focused on recurring Estimates, but the engine, data model, and UI are built to extend. Items are sequenced roughly by value and effort; several were non-goals in Section 3.3 and have reserved room in the schema.

## **22.1 Customer acceptance & deposits**

* **Portal e-acceptance / e-signature.** Let customers accept, decline, or e-sign an estimate from a secure link, auto-updating status — the Sent→Accepted hook is already in place.

* **Deposit / retainer on acceptance.** Optionally create a deposit invoice (a liability/deferred-revenue entry) when an estimate is accepted.

* **Auto-convert on acceptance.** Automatically create a draft invoice (and optionally email it) the moment a customer accepts.

## **22.2 Invoicing depth**

* **Scheduled progress-invoicing plans.** Define milestones/percentages that auto-invoice an accepted estimate over time.

* **Markup rules.** Apply default markups when building a quote from cost.

* **Estimate versions & approval.** Track revisions of a quote and require internal approval before sending high-value estimates.

## **22.3 Lifecycle & scale**

* **Pause / Resume / Skip.** Temporarily halt or skip a single occurrence without deleting the template.

* **Bulk import/export & bulk edit.** CSV import of templates and cross-template edits.

* **Custom frequencies & multi-currency.** “Last weekday of the month” style rules and per-template currency with FX applied on the converted invoice.

* **More recurring sales types.** Recurring Invoice and Sales Receipt on the same engine (posting siblings of the estimate).

# **23\. Appendix**

## **23.1 Field quick-reference**

| Field | Meaning | Detail in |
| :---- | :---- | :---- |
| Template name | Human label for the recurring estimate | §9.3, §13 |
| Type | Scheduled / Reminder / Unscheduled behavior | §7, §9.3, §11 |
| Customer | Who the quote is for — required | §9.3, §15 |
| Email / Cc / Bcc | Where the estimate PDF is sent | §9.3, §19 |
| Online payments | Card/bank options carried to the invoice | §9.3 |
| Billing / Shipping addresses | Customer and fulfilment addresses | §9.3 |
| Service date (line) | When the service is/was rendered | §9.3 |
| Discount / Sales tax / Shipping | Pricing shown on the quote (posts on the invoice) | §9.3, §11.9, §12 |
| Interval | Frequency \+ day-of-month / weekday \+ every-N | §9.3, §11.1 |
| source\_template\_id / linked\_invoice\_id | Links an estimate to its template and its converted invoice | §13 |

## **23.2 Type-behavior summary**

| Behavior | Scheduled | Reminder | Unscheduled |
| :---- | :---- | :---- | :---- |
| Auto-creates estimate | **Yes** | **No** | **No** |
| Can auto-email customer | Yes | No | No |
| Has a timetable | Yes | Yes | — |
| Appears in Reminders List | No | Yes | No |
| Primary way to create | Automatic on due date | Create from reminder | Use from the list |

## **23.3 Estimate status lifecycle**

| Status | Meaning | Posts? |
| :---- | :---- | :---- |
| Draft | Created, not yet sent | No |
| Sent (Pending) | Emailed, awaiting customer decision | No |
| Accepted | Customer approved; ready to invoice | No |
| Declined | Customer rejected (kept for record) | No |
| Expired | Validity date passed (kept for record) | No |
| Invoiced (Closed) | Converted, fully or partially | Only the invoice does |

## **23.4 Estimate vs Invoice vs Sales Receipt — cheat-sheet**

|  | Estimate | Invoice | Sales Receipt |
| :---- | :---- | :---- | :---- |
| Posts to ledger? | **No** | Yes | Yes |
| Represents | A proposal | Money owed | Money received |
| Debit side | — (none) | **Accounts Receivable** | Bank / Undeposited |
| Credit side | — (none) | Income (+ tax) | Income (+ tax) |
| Customer pays | Not yet | Later (on terms) | At point of sale |

## **23.5 Conversion posting quick-reference**

| Convert estimate to… | Posting on the resulting transaction |
| :---- | :---- |
| Invoice | Dr Accounts Receivable; Cr Income; Cr Sales Tax Payable. |
| Invoice (with discount) | Dr A/R; Dr Sales Discounts (contra-income); Cr Income; Cr Sales Tax Payable. |
| Sales Receipt | Dr Bank / Undeposited Funds; Cr Income; Cr Sales Tax Payable. |
| Progress invoice | Same accounts, for the invoiced portion only; estimate stays open. |
| (The estimate itself) | Nothing — always non-posting. |

## **23.6 The sales-side & purchase-side family**

|  | Non-posting (proposal) | Posting (real) |
| :---- | :---- | :---- |
| Sales side | **Estimate (this module)** | Invoice / Sales Receipt |
| Purchase side | Purchase Order | Bill / Expense / Cheque |

*All of these share one scheduling engine; each posting transaction carries its own journal entry, while the two proposals (Estimate and Purchase Order) post nothing until converted.*

## **23.7 Change log**

| Version | Date | Change |
| :---- | :---- | :---- |
| 1.0 | Initial | First release for build: Recurring Estimate with Scheduled / Reminder / Unscheduled types, customer & auto-email, online-payment options, delivery details, line items with service date and per-line tax, discount and sales tax and shipping, customer messages, estimate numbering, the Draft→Sent→Accepted/Declined/Expired→Invoiced lifecycle, non-posting behavior with one-click conversion to an invoice/sales receipt (including progress invoicing), scheduling engine, data model, APIs, and QA checklist. |

*End of document.*