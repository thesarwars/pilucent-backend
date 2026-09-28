

| BALANZIFY   ·   PRODUCT DOCUMENTATION A/R Aging Detail Report Logic · Calculations · Filtering · Columns · Data Representation · Use Cases |
| :---- |

This guide explains exactly how Balanzify builds the Accounts Receivable (A/R) Aging Detail Report. It walks through every column, the formulas behind each figure, how transactions are sorted into aging buckets, the filtering and customization options available to you, and the day-to-day decisions the report is designed to support. It is written for business owners, bookkeepers, accountants, and anyone on the finance team who needs a clear picture of what customers owe and when it is due.

**Module:**  Accounts Receivable · Reporting        **Report type:**  Detail        **Version:**  1.0

Audience: Finance, Accounting & Bookkeeping teams

Last updated: June 2026

**Contents**

**1  Introduction**3

1.1  About this guide3

1.2  What the A/R Aging Detail Report is3

1.3  Why it matters3

**2  Key concepts and terminology**4

**3  How to read the report**4

3.1  The regions of the report4

3.2  The aging bands5

**4  Column reference**5

**5  Aging logic: how items land in a bucket**6

5.1  The aging date basis6

5.2  The default buckets6

5.3  The assignment rule6

5.4  Credits and items without a due date7

**6  Calculations**7

**7  Report period and date settings**7

**8  Filtering and customization**8

8.1  The Customize panel8

8.2  Columns you can add8

**9  Data representation and formatting**9

**10  Transaction types included**9

**11  Worked example: the sample report**9

11.1  The data9

11.2  How the key numbers are derived10

11.3  A quick reconciliation check11

**12  Common use cases**11

**13  Best practices**11

**14  FAQ and troubleshooting**11

**15  Quick reference (cheat sheet)**12

# **1  Introduction**

## **1.1  About this guide**

Balanzify reports are most useful when you know precisely what each number means and where it comes from. This document removes the guesswork from the A/R Aging Detail Report. By the end of it you should be able to read any line on the report with confidence, reproduce every total by hand, and adjust the report so it answers the specific question in front of you — whether that is “who owes us right now?”, “what is dangerously overdue?”, or “does this balance tie out at month-end?”

## **1.2  What the A/R Aging Detail Report is**

**Accounts Receivable (A/R)** is the money your customers owe your business for goods or services you have delivered but have not yet been paid for. The A/R Aging Detail Report takes every **open** (unpaid) receivable in your books and lists it transaction by transaction, organized by how overdue it is. Instead of a single lump sum, you see each individual invoice and credit memo: who owes it, when it was due, how many days it has been outstanding, and how much is still open.

The word **Detail** is the important part. Balanzify offers two closely related reports built from the same data:

* **A/R Aging Summary —** collapses everything into one row per customer, spread across a set of aging columns. It answers “how much, and how old, per customer.”

* **A/R Aging Detail (this report) —** expands those balances into every underlying transaction. It answers “exactly which invoices and credits make up that balance.”

Use the Summary for a quick health check and the Detail when you need to act on, verify, or explain a specific number.

## **1.3  Why it matters**

* It tells you who owes you and when, so you can forecast incoming cash and plan around it.

* It surfaces overdue invoices early — before they slide toward collections or bad debt.

* It lets you prioritize — chase the oldest or largest balances first.

* It exposes unapplied customer credits and overpayments you can put to work against open invoices.

* It supports month-end close: the report’s total open balance should reconcile to the Accounts Receivable balance on your Balance Sheet.

| At a glance Report family — Detail — one row per transaction. Source — Your Accounts Receivable account(s). Shows — Open (unpaid) invoices and unapplied credit memos only — fully settled items drop off. Default grouping — Aging bands — Current, 1–30, 31–60, 61–90, and 91+ days past due. Default sort — Due date, oldest first. Signs — Invoices are positive; credit memos and customer payments are negative. Key figure — Open balance \= what the customer still owes (or you still hold as a credit) today. |
| :---- |

# **2  Key concepts and terminology**

A handful of terms appear throughout the report and this guide. Skim these once and the rest of the document reads easily.

| Term | What it means |
| :---- | :---- |
| **Accounts Receivable (A/R)** | Money your customers owe you for goods or services delivered but not yet paid. |
| **Receivable** | A single amount a customer owes you — most often an invoice. |
| **Aging** | Sorting open receivables by how long they have been outstanding, i.e. how overdue they are. |
| **Aging bucket (interval)** | A date range used to group items, such as “1–30 days past due.” |
| **Invoice** | A request for payment you send a customer. It increases A/R (positive). |
| **Credit memo** | A credit you issue a customer (a return, refund, or adjustment) that reduces what they owe. Shown as a negative amount. |
| **Due date** | The date an invoice must be paid, set by the payment terms (e.g. Net 30). |
| **Past due (days)** | How many days an item is overdue, measured from its due date to the report date. |
| **Open balance** | The unpaid (or unapplied) portion still outstanding on a transaction. |
| **As-of / report date** | The point in time the report is calculated for — the date aging is measured against. |
| **Report period** | The date setting that controls which transactions are included and the as-of date used. |

# **3  How to read the report**

## **3.1  The regions of the report**

From top to bottom, the report is organized into a few predictable regions. Knowing what each one does makes the whole report easy to scan.

| Region | Where it is | What it does |
| :---- | :---- | :---- |
| **Report title** | Top, centered | Names the report — “A/R Aging Detail Report” — under your company name. |
| **Report period** | Top-left control | Sets the date range and as-of date for the whole report (see Section 7). |
| **Toolbar** | Top-right icons | View/zoom, refresh, email, print, and export (spreadsheet or PDF). |
| **Column headers** | Below the title | Label each column; the small arrows sort rows within each band. |
| **Aging band header** | Shaded row with a count | Starts a group, e.g. “CURRENT (2).” The number is the count of lines in that band. |
| **Detail rows** | Under each band | One transaction per line — the heart of the report. |
| **Band subtotal** | “Total for …” row | Sums Amount and Open balance for that band. |
| **Grand total** | “TOTAL” row at the bottom | Sums every band into a single A/R figure. |

## **3.2  The aging bands**

Every open item is filed into exactly one aging band based on how overdue it is. Reading the bands from top to bottom takes you from the most overdue items to the least (or the reverse, depending on your sort). Bands with no qualifying transactions are simply omitted — that is why the sample report shows only the “CURRENT” band: every open invoice in it is dated today and due next month, so nothing has aged into the overdue bands yet.

# **4  Column reference**

Below is every default column on the report, what it shows, and where its value comes from. You can add, remove, and reorder columns under Customize (Section 8\) — including a Past due column that prints the exact day count behind each band.

| Column | What it shows | Where it comes from / how it is calculated |
| :---- | :---- | :---- |
| **Date** | The date the transaction was recorded. | Taken straight from the transaction — the invoice date or the credit-memo date. Also used as the aging basis when a line has no due date. |
| **Transaction type** | The kind of receivable — usually Invoice or Credit Memo. | Tells you whether the line increases what the customer owes (Invoice, positive) or reduces it (Credit Memo, negative). |
| **Num** | The reference or document number. | Pulled from the transaction’s number field — the invoice number (1030 and 1031 in the sample). Blank if none was entered (common for credit memos). |
| **Customer full name** | The customer the receivable is owed by. | The name as it appears in your customer list. Group or filter by this to see one customer at a time. |
| **Store full name** | The store, location, or class assigned. | Only meaningful if you track multiple locations. Blank when no location is assigned. |
| **Due date** | When payment is due from the customer. | Invoice date \+ payment terms (e.g. Net 30). This is the date the aging clock counts from. Credit memos usually have none. |
| **Amount** | The original, full value of the transaction. | Invoices positive, credit memos negative. Does not change as payments are received. |
| **Open balance** | What is still outstanding right now. | Amount − payments/credits already applied. Equals Amount when nothing has been settled. This is the real “what they owe today.” |

# **5  Aging logic: how items land in a bucket**

## **5.1  The aging date basis**

The report ages each open item by comparing a reference date — the **as-of date** — to the item’s **due date**. The number of whole days between them is the item’s days past due. When the Report period is set to **All Dates**, the as-of date is simply today, so the report shows what is overdue as of the moment you run it.

| days\_past\_due  \=  as\_of\_date  −  due\_date   • result ≤ 0   → not yet due (belongs in “Current”); Past due shows 0 / blank • result ≥ 1   → overdue by that many days |
| :---- |

## **5.2  The default buckets**

Balanzify files items into these standard bands. Reading them as a ladder, “Current” sits at the top (nothing overdue) and each step down is another period of lateness.

* **Current** — due today or in the future (0 days past due).

* **1 – 30 days past due**

* **31 – 60 days past due**

* **61 – 90 days past due**

* **91 or more days past due** (91+).

These bands come from two settings you can change under Customize: the **number of days in each aging period** (default 30\) and the **number of periods** (default 4). “30 days × 4 periods” produces the 1–30 / 31–60 / 61–90 / 91+ structure plus the Current band.

## **5.3  The assignment rule**

In plain terms, the report walks the days-past-due value through a simple ladder and stops at the first band it fits:

| days \= as\_of\_date − due\_date   if   days \<= 0 :  band \= "Current" elif days \<= 30:  band \= "1 \- 30 days past due" elif days \<= 60:  band \= "31 \- 60 days past due" elif days \<= 90:  band \= "61 \- 90 days past due" else           :  band \= "91 or more days past due" |
| :---- |

## **5.4  Credits and items without a due date**

Credit memos reduce what a customer owes and normally carry no payment due date. When a transaction has no due date, Balanzify ages it by its transaction date instead — so a credit memo dated several months ago would appear in an older band even though its Due date and Past due columns are blank. In the sample report there are no credit memos: both invoices are dated 06/24/2026 and due 07/24/2026, so — measured against the as-of date — they are not yet due and sit together in the “CURRENT” band.

# **6  Calculations**

Every figure on the report can be reproduced with a few simple rules.

**6.1  Past due (days).**  Past due \= as-of date − Due date. A negative or zero result means the item is not yet due, so the line lands in Current and Past due reads 0 (or blank). A positive result is the number of days late, and it decides the aging band. In the sample, both invoices are due 07/24/2026 against an as-of date of 06/24/2026 — 30 days in the future — so their days-past-due is negative and both fall into Current.

**6.2  Open balance.**  Open balance \= Amount − (payments or credits already applied to that transaction). When nothing has been received or applied, Open balance equals Amount — which is exactly what the sample shows: invoice 1030 reads 49,331.25 in both columns, and invoice 1031 reads 3,330.75 in both. If the customer later paid part of an invoice, its Open balance would fall below its Amount while the Amount itself stayed unchanged.

**6.3  Sign conventions.**  Invoices are positive because they increase A/R. Credit memos are negative because they reduce it. Customer payments, once applied, lower the open balance of the invoices they pay; an invoice that is paid in full has a zero open balance and therefore drops off the report entirely. The report only ever lists transactions whose open balance is not zero as of the report date.

**6.4  Subtotals and the grand total.**  Each band shows a “Total for …” row that sums the Amount and Open balance columns for the lines in that band. Because credit memos are negative, a band’s subtotal naturally nets invoices against credits. The “TOTAL” row at the bottom sums all bands into your overall A/R position. In the sample there is only one band, so the “Total for CURRENT” row (52,662.00) and the grand TOTAL are identical.

# **7  Report period and date settings**

The Report period control (top-left) drives the dates the report uses, alongside an explicit “as of” date. The sample is set to Today with an as-of date of 06/24/2026. The dropdown offers a standard set of ready-made ranges plus a custom option:

| Option | What it does |
| :---- | :---- |
| **All Dates** | Includes every open receivable and ages it as of the current date. A common choice for a true “what are we owed right now” view. |
| **Custom dates** | You pick a specific From/To range and as-of date — useful for historical or point-in-time aging. |
| **Today** | Limits to today and ages as of today (the setting used in the sample). |
| **This week / to date** | The current calendar week — the whole week, or only up to today. |
| **This fiscal week** | The current week on your fiscal calendar. |
| **This month / to date** | The current month — whole month, or up to today. |
| **This quarter / This fiscal quarter** | The current (calendar or fiscal) quarter; “to date” variants stop at today. |
| **This year / This fiscal year** | The current (calendar or fiscal) year; “to date” variants stop at today. |
| **Last week / month / quarter / year** | The matching prior period (further down the list). |

The dropdown scrolls, so the list continues with the “…to date,” fiscal, and “Last …” variants. For an aging report specifically, the period mainly sets which transactions are in scope and the as-of date used for aging; the size of the buckets and the aging method are configured separately under Customize.

# **8  Filtering and customization**

## **8.1  The Customize panel**

The Customize button opens a panel where you reshape the report. The most useful controls are grouped here:

* **General —** report period, accounting method (Accrual or Cash), and number format — show or hide cents, divide by 1,000, hide zero amounts, and show negatives in red or in parentheses.

* **Rows / Columns —** choose which columns appear and in what order, toggle the aging grouping, and set the sort column and direction.

* **Aging —** the aging method (age by report date, or by today’s date), the number of days per aging period (default 30), and the number of periods (default 4).

* **Filter —** narrow the report by Customer, Transaction type, Store/Location, or A/R account when you keep more than one.

* **Header / Footer —** control the company name, report title, the prepared date/time, and page numbers shown on the printed report.

Once a report looks the way you want, use Save As to keep it as a custom report you can reopen with one click.

## **8.2  Columns you can add**

Beyond the defaults, you can surface extra columns when you need more context. Common additions include:

* Past due (the exact number of days each line is overdue — the day count behind the aging bands)

* Account (the income or A/R account the invoice posts to)

* Memo / Description

* Terms (e.g. Net 15, Net 30\)

* Currency and exchange rate (for multi-currency books)

* Created date, Last modified, and Last modified by (for audit trails)

# **9  Data representation and formatting**

How the report displays its data is just as important as the numbers themselves:

* **Grouping —** rows are grouped into aging bands; each band carries a header (with a line count) and a subtotal.

* **Sorting —** the arrows in each column header sort rows within each band. The default is Due date, ascending — so within a band, dated invoices appear oldest-first and items without a due date (such as credit memos) follow.

* **Signs and emphasis —** invoices are positive and credit memos negative; via number format, negatives can be shown in red or wrapped in parentheses. Subtotals and the grand total are bold and separated by a rule line.

* **Collapse / expand —** the chevron beside each band header collapses that band down to just its subtotal, which is handy when you only care about totals.

* **Zoom and density —** the “Normal | 100%” control adjusts zoom and the on-screen density.

* **Share and export —** the toolbar lets you refresh, email, print, or export the report to a spreadsheet or PDF, preserving the grouping and totals.

# **10  Transaction types included**

Any transaction that posts to your Accounts Receivable account and still has an open balance can appear. The most common are:

* **Invoice —** a receivable a customer owes you. Positive; carries a due date based on its terms.

* **Credit Memo —** a credit you issue a customer that offsets what they owe. Negative; usually no due date, so it ages by its own date.

* **Payment —** a customer payment applied to one or more invoices. It reduces the open balance of those invoices; if an invoice is paid in full it nets away and drops off the report.

Journal entries and other transactions that post directly to the A/R account with an open balance can also surface here. Estimates and sales receipts do not — an estimate is only a proposal, not a posted receivable, and a sales receipt is paid at the point of sale, so it never leaves an open balance to age.

# **11  Worked example: the sample report**

## **11.1  The data**

Here is a faithful recreation of the sample A/R Aging Detail Report for Halo Axis. It is aged as of June 24, 2026\. Both invoices were issued on 06/24/2026 on Net-30 terms, putting their due date at 07/24/2026 — still in the future — so both sit in the Current band and the report shows no overdue groups at all.

| Date | Transaction type | Num | Customer full name | Store full name | Due date | Amount | Open balance |
| :---- | :---- | :---- | :---- | :---- | :---- | ----: | ----: |
| **CURRENT (2)** |  |  |  |  |  |  |  |
| 06/24/2026 | Invoice | 1030 | France |  | 07/24/2026 | 49,331.25 | 49,331.25 |
| 06/24/2026 | Invoice | 1031 | JumaTechs |  | 07/24/2026 | 3,330.75 | 3,330.75 |
| **Total for CURRENT** |  |  |  |  |  | **$52,662.00** | **$52,662.00** |
| **TOTAL** |  |  |  |  |  | **$52,662.00** | **$52,662.00** |

## **11.2  How the key numbers are derived**

**Why both lines are Current.** Invoice 1030 (France) and invoice 1031 (JumaTechs) are each due 07/24/2026. Counting from the as-of date of 06/24/2026, the due date is 30 days away, so days-past-due is −30. A result of 0 or less means “not yet due,” which places both lines in Current; that is also why no Past due value is shown for them.

**Open balance.** Neither invoice has received a payment, so each line’s Open balance equals its Amount — 49,331.25 for France and 3,330.75 for JumaTechs.

**Band subtotal (Current).** Add the two invoices together:

| Amount        \=  49,331.25 \+ 3,330.75   \=   52,662.00 Open balance  \=  49,331.25 \+ 3,330.75   \=   52,662.00 |
| :---- |

**Grand total.** With only the Current band populated, the “TOTAL” row simply repeats the band subtotal: Amount 52,662.00 and Open balance 52,662.00 — the figures shown at the foot of the report.

| Illustration — how the same invoice would age Suppose invoice 1030 were still unpaid when you ran the report on 09/05/2026. Measured from its due date of 07/24/2026, it would now be 43 days past due, so it would move out of Current and into the “31 – 60 days past due” band. Its Amount would stay 49,331.25, but its Open balance would reflect any partial payments received in the meantime — and once it was paid in full, the line would disappear from the report entirely. |
| :---- |

## **11.3  A quick reconciliation check**

In this sample the Amount and Open balance totals are identical (52,662.00) because no customer payments or credit memos have been applied yet. The moment a customer pays part of an invoice, or you issue a credit memo, the two totals diverge: Open balance drops below Amount by the net of those payments and credit applications. The Open balance total — here 52,662.00 — is the figure that should reconcile to the Accounts Receivable balance on your Balance Sheet for the same as-of date.

# **12  Common use cases**

The report earns its keep in everyday finance work. A few of the most common ways teams use it:

1. **Forecast incoming cash.** Read the open balances and due dates to project when receivables will turn into cash and plan around it.

2. **Prioritize collections.** Focus on the 61–90 and 91+ bands, or on the largest balances, to chase the right customers first.

3. **Head off bad debt.** The oldest bands flag invoices at risk of going uncollectible, so you can follow up before it is too late.

4. **Manage customer credit risk.** Spot customers who repeatedly pay late or carry large overdue balances and revisit their terms or credit limit.

5. **Put customer credits to work.** Surface unapplied credit memos and overpayments (negative open balances) and apply them to open invoices.

6. **Close the month and answer disputes.** Tie the total open balance back to the A/R balance on the Balance Sheet, and drill from any balance into the exact invoice or credit behind it.

# **13  Best practices**

* Run the report on a regular cadence (weekly is common) so overdue invoices never pile up unnoticed.

* Reconcile the total open balance to the Accounts Receivable balance on your Balance Sheet at month-end; investigate any difference.

* Watch the 91+ band closely — long-overdue invoices signal collection problems or, sometimes, a data-entry error.

* Investigate negative open balances — usually an unapplied payment or credit memo that should be applied to an open invoice.

* Confirm each customer’s payment terms are set correctly; the due date — and therefore the entire aging — depends on them.

* Save a customized version (filtered to a customer or location, or with the Past due column added) so your go-to view is one click away.

# **14  FAQ and troubleshooting**

**Q.  Why is an invoice I know about missing from the report?**

**A.**  Most likely it has been paid in full, so its open balance is zero and it drops off. Check that the invoice falls inside the selected report period as well.

**Q.  Why are some amounts negative?**

**A.**  Negative lines are credit memos (or unapplied customer payments). They reduce what the customer owes, so they carry a negative Amount and Open balance.

**Q.  Why does a credit memo appear in an older band with no due date?**

**A.**  Credit memos usually have no due date, so they are aged by their transaction date. A credit dated months ago lands in an older band even though Due date and Past due are blank.

**Q.  Why don’t the Amount and Open balance totals match?**

**A.**  Because some invoices have been partially paid or had credits applied. The difference equals the net of those payments and credit applications. (In the sample they match, because nothing has been applied yet.)

**Q.  What’s the difference between this and the A/R Aging Summary?**

**A.**  The Summary shows one netted row per customer across aging columns; the Detail (this report) lists every individual transaction behind those balances.

**Q.  How do I change the aging buckets?**

**A.**  Open Customize → Aging and adjust the days per period and the number of periods. The bucket headings update automatically.

**Q.  Why is an item in “Current” when its date is in the past?**

**A.**  Current is based on the due date, not the transaction date. The sample shows exactly this: invoices dated 06/24/2026 are due 07/24/2026, so they are not yet overdue and sit in Current.

**Q.  The total doesn’t match my Balance Sheet — what now?**

**A.**  Confirm both use the same as-of date and accounting method (Accrual vs Cash), then look for entries posted directly to A/R or items dated outside the report period.

# **15  Quick reference (cheat sheet)**

| Formulas Past due (days) — as-of date − Due date  (≤ 0 ⇒ Current) Open balance — Amount − payments/credits already applied Band subtotal — sum of Amount and of Open balance for lines in the band (invoices − credits) Grand total — sum of all band subtotals |
| :---- |

| Reading the bands Current — due today or later (0 days past due) 1 – 30 / 31 – 60 / 61 – 90 — increasing degrees of lateness, 30 days apart 91 or more — the most overdue — chase this band first Empty bands — are hidden; only bands with transactions appear |
| :---- |

Balanzify · Accounts Receivable Reporting · A/R Aging Detail Report