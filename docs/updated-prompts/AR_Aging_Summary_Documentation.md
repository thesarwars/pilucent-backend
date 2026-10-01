  
**PILUCENT**

Accounting & Bookkeeping Platform

**Accounts Receivable (A/R)**

**Aging Summary Report**

Product & Reporting Documentation

*Logic · Calculations · Filtering · Columns · Data Representation · Use Cases*

| Document | A/R Aging Summary Report — Functional Specification |
| :---- | :---- |
| **Module** | Reports → Receivables → A/R Aging Summary |
| **Audience** | Business owners, bookkeepers, accountants, A/R & collections staff |
| **Version** | 1.0 |
| **Status** | Released |

**Table of Contents**

[**1\. Introduction & Overview	3**](#heading=)

[1.1 What the report answers	3](#heading=)

[1.2 Who uses it	3](#heading=)

[1.3 Where it sits in the receivables workflow	3](#heading=)

[**2\. Key Concepts & Terminology	5**](#heading=)

[**3\. Anatomy of the Report	6**](#heading=)

[3.1 The control strip	6](#heading=)

[3.2 The report header	6](#heading=)

[3.3 The data grid	6](#heading=)

[3.4 The footer	6](#heading=)

[**4\. Columns Explained	7**](#heading=)

[**5\. The Aging Logic (Core Engine)	8**](#heading=)

[5.1 Step one — establish the aging date	8](#heading=)

[5.2 Step two — measure days outstanding	8](#heading=)

[5.3 Step three — assign the bucket	8](#heading=)

[5.4 Worked micro-examples	8](#heading=)

[**6\. Calculation Methodology	10**](#heading=)

[6.1 Pass 1 — per transaction	10](#heading=)

[6.2 Pass 2 — per customer (each row)	10](#heading=)

[6.3 Pass 3 — per column (the bottom row)	10](#heading=)

[6.4 Pass 4 — the grand total	10](#heading=)

[**7\. What Data Appears on the Report	11**](#heading=)

[7.1 Transactions that change A/R	11](#heading=)

[7.2 Open balances only	11](#heading=)

[7.3 Why some balances are negative	11](#heading=)

[7.4 Accounting basis	11](#heading=)

[**8\. Filtering & Customization	12**](#heading=)

[**9\. Data Representation & Formatting	13**](#heading=)

[**10\. Worked Example — Reading a Real Report	14**](#heading=)

[10.1 The report as displayed	14](#heading=)

[10.2 Reading each customer row	14](#heading=)

[10.3 Verifying the totals	14](#heading=)

[**11\. Reconciliation & Validation	16**](#heading=)

[11.1 The key relationship	16](#heading=)

[11.2 Common reasons they might differ	16](#heading=)

[**12\. Use Cases & Business Scenarios	17**](#heading=)

[**13\. Best Practices	18**](#heading=)

[**14\. FAQ & Troubleshooting	19**](#heading=)

[**15\. Glossary	20**](#heading=)

# **1\. Introduction & Overview**

The Accounts Receivable (A/R) Aging Summary Report in Pilucent gives you a clear, single-screen picture of every unpaid amount your customers owe your business — organized by how long each balance has been outstanding. Rather than scrolling through individual invoices, you see one consolidated line per customer, with that customer’s open balance spread across a row of time-based “aging” columns.

In plain terms, the report turns a long list of invoices into a short, prioritized snapshot. It is one of the most frequently used reports in any bookkeeping routine because it connects directly to cash: it tells you who owes you money, how much, and how overdue each amount has become — which is exactly what you need to manage collections and forecast incoming cash.

## **1.1 What the report answers**

A single A/R Aging Summary is designed to answer three questions at a glance:

* **Who owes us money?** Each customer with an open balance appears on its own row.

* **How much does each of them owe?** The Total column shows the net balance per customer, and the bottom Total row shows the company-wide receivable.

* **How overdue is each amount?** The aging columns split every balance by the number of days it is past due, so genuinely late invoices stand apart from amounts that are still within terms.

## **1.2 Who uses it**

| Role | Why they rely on it |
| :---- | :---- |
| **Business owner / founder** | Quick read on near-term incoming cash and which customers are slow to pay. |
| **Bookkeeper** | Daily and month-end check that receivables are accurate and that nothing has quietly slipped overdue. |
| **Accountant / Controller** | Reconciles the report total to the Accounts Receivable balance on the Balance Sheet, reviews aging health, and informs the allowance for doubtful accounts. |
| **A/R clerk / Collections** | Works the list from oldest to newest, sending reminders and chasing down overdue invoices and billing disputes. |
| **Auditor / Reviewer** | Tests the completeness and valuation of receivables as of a specific date, including likely bad debt. |

## **1.3 Where it sits in the receivables workflow**

Every time you create an invoice, apply a customer payment, or issue a credit memo, Pilucent updates the underlying Accounts Receivable ledger. The A/R Aging Summary is the reporting lens placed over that ledger. It does not create or change any data — it reads the current open balances and re-presents them by age. Because of this, the report is always only as accurate as the invoices, credits, and payments behind it.

| Summary vs. Detail Pilucent offers two related reports. The A/R Aging Summary (this document) shows one rolled-up row per customer. The A/R Aging Detail report breaks the same balances down into the individual transactions — each invoice, its date, due date, and open amount. Whenever you need to see what makes up a number on the Summary, drill into the Detail. |
| :---- |

# **2\. Key Concepts & Terminology**

A few core ideas drive everything in this report. Getting comfortable with them makes the calculations and settings that follow easy to read.

| Term | Meaning in Pilucent |
| :---- | :---- |
| **Accounts Receivable (A/R)** | The money your customers owe your business for goods or services delivered but not yet paid for. It is an asset. |
| **Invoice** | A transaction recording an amount a customer owes you. Creating an invoice increases A/R. |
| **Customer payment** | A transaction that settles all or part of an invoice. It decreases A/R. An invoice can be paid in several installments. |
| **Credit memo** | An amount you owe back to a customer (a return, allowance, or correction). It decreases A/R and can appear as a negative balance until applied. |
| **Open balance** | The portion of a transaction still unpaid or unapplied. Only open balances appear on the report; fully settled items drop off. |
| **Due date** | The date an invoice is scheduled to be paid, usually derived from the invoice date plus the customer’s payment terms (for example, Net 30). |
| **Transaction date** | The date written on the invoice itself — typically when the goods or services were billed. |
| **Aging date (as-of date)** | The reference date the report uses to measure how old each balance is. Everything is aged relative to this single date. |
| **Aging bucket / period** | A range of days (for example, 31–60) into which a balance is placed based on how overdue it is. |

# **3\. Anatomy of the Report**

The screen is made up of a small control strip, a report header, the data grid, and a footer. Knowing each region makes the rest of this document easier to follow.

## **3.1 The control strip**

Running across the top of the report are the controls used to shape and share it:

* **Report period & as-of date —** choose the date basis for the report. In the worked example this is “Today,” with an as-of date of 06/24/2026.

* **Customize —** opens the full settings panel: aging method, days per period, number of periods, filters, columns, and header/footer options.

* **Save As —** stores your customized version as a reusable saved report so you do not have to re-set the options each time.

* **Refresh, Email, Print, Export —** regenerate the figures, send the report, print it, or export it to a spreadsheet or PDF.

* **Compact and zoom —** toggle a denser layout and scale the on-screen size (for example, 100%). These affect display only, never the numbers.

## **3.2 The report header**

Centered above the grid, the header identifies exactly what you are looking at:

* **Company name** — the business the report belongs to (for example, Halo Axis).

* **Report title** — “A/R Aging Summary Report.”

* **Date basis** — the as-of line (for example, “As of June 24, 2026”).

## **3.3 The data grid**

The body is a simple matrix. Each row is a customer; each column is an aging bucket, with a Total column on the right. The bottom row totals every column down the page. A sort control on the Total column header lets you rank customers by the size of their balance.

## **3.4 The footer**

Below the grid, Pilucent stamps the exact date and time the report was generated, along with the time zone (for example, Wednesday, June 24, 2026 02:20 PM GMT+06:00). This timestamp matters: because aging is measured against a reference date, two copies of the same report run on different days can legitimately show different numbers. There is also an option to attach a note for context.

# **4\. Columns Explained**

With the default settings (30 days per period and four periods), the report shows the following columns from left to right. The customer name occupies the first, unlabeled column.

| Column | What it represents | Days past due |
| :---- | :---- | :---: |
| **Customer** | The customer the balance is owed by. One row per customer with any open balance. | — |
| **Current** | Balances that are not yet overdue — still within their payment terms as of the aging date. | 0 or not yet due |
| **1 – 30** | Balances that became overdue within the last month. | 1 to 30 days |
| **31 – 60** | Balances overdue by one to two months. | 31 to 60 days |
| **61 – 90** | Balances overdue by two to three months. | 61 to 90 days |
| **91 and over** | Long-overdue balances; the catch-all for anything older than the last defined period. The most likely to become bad debt. | 91+ days |
| **Total** | The customer’s net open balance — the sum of all aging columns on that row. | All ages combined |

| About the column count and width The exact number of aging columns is configurable. The default of four 30-day periods produces Current, 1–30, 31–60, 61–90, and 91 and over. Changing “days per period” or “number of periods” in Customize re-labels and re-bands these columns automatically (see Section 8). |
| :---- |

# **5\. The Aging Logic (Core Engine)**

Aging is the heart of this report. Strip everything else away and the question is simple: for each open balance, how many days late is it, and therefore which column does it belong in?

## **5.1 Step one — establish the aging date**

Every balance is measured against a single reference date, called the aging date. By default this is the end of the selected report period. When the period is set to “Today,” the aging date is the current date — in the worked example, June 24, 2026\. (The aging method setting, covered in Section 8, lets you base it on the current date or the report date explicitly.) This is why the footer timestamp is important: it records the moment that drove the aging.

## **5.2 Step two — measure days outstanding**

For each open transaction, Pilucent calculates how many days have elapsed between its due date and the aging date:

| Days Past Due  \=  Aging Date  −  Due Date |
| :---: |

A positive result means the balance is overdue by that many days. A result of zero or below means it is *not yet due* and is therefore considered current.

| Which date drives aging: due date vs. transaction date By default, Pilucent ages each balance from its due date — the most common and intuitive choice, because an invoice is only “late” once its due date has passed. If you prefer, the aging method can instead measure from the transaction (invoice) date, which ages everything from when it was issued regardless of terms. The bucket boundaries below work identically either way; only the date you subtract changes. |
| :---- |

## **5.3 Step three — assign the bucket**

The number of days past due maps to exactly one column using these rules (default 30-day periods):

| Condition | Days past due | Goes into column |
| :---- | :---: | :---- |
| Not yet due / due today | **≤ 0** | **Current** |
| Recently overdue | **1 to 30** | **1 – 30** |
| Overdue 1–2 months | **31 to 60** | **31 – 60** |
| Overdue 2–3 months | **61 to 90** | **61 – 90** |
| Long overdue | **≥ 91** | **91 and over** |

## **5.4 Worked micro-examples**

Assume the report is run on June 24, 2026, so the aging date is June 24, 2026\.

* **An invoice due July 5, 2026** → due date is in the future, days past due is negative → **Current**.

* **An invoice due June 10, 2026** → 14 days past due → **1 – 30**.

* **An invoice due April 20, 2026** → 65 days past due → **61 – 90**.

* **An invoice due January 2, 2026** → 173 days past due → **91 and over**.

| Each transaction ages on its own A customer can appear in more than one column at once. If a customer owes you on an old invoice and you have also issued them a recent credit memo, the invoice and the credit are aged separately and land in different columns. Only the Total column nets them together. Section 10 shows how a multi-bucket customer would read. |
| :---- |

# **6\. Calculation Methodology**

The report is built in four passes: per transaction, per customer, per column, and finally the grand total. Each pass is a straightforward sum, which is what makes the report fast and easy to verify by hand.

## **6.1 Pass 1 — per transaction**

1. Take the open balance of every unpaid invoice, unapplied credit memo, and any A/R journal entry.

2. Compute days past due for each using the formula in Section 5.2.

3. Drop each open balance into its matching aging bucket. Credit memos and overpayments carry a negative sign.

## **6.2 Pass 2 — per customer (each row)**

All of a customer’s bucketed amounts are grouped onto a single row, then summed across to produce the Total for that customer:

| Customer Total  \=  Current \+ (1–30) \+ (31–60) \+ (61–90) \+ (91 and over) |
| :---: |

## **6.3 Pass 3 — per column (the bottom row)**

Each aging column is summed straight down the page across all customers, producing the column totals on the Total row.

| Column Total  \=  Σ (that column’s amount for every customer) |
| :---: |

## **6.4 Pass 4 — the grand total**

The bottom-right figure is the company-wide net receivable. It can be reached two independent ways, and the two must agree — a built-in cross-check:

* **Across the bottom row:** sum of all column totals.

* **Down the Total column:** sum of all customer totals.

| Σ Column Totals   \=   Σ Customer Totals   \=   Grand Total |
| ----- |
| **A handy validation** If the two ways of reaching the grand total ever disagree, the data behind the report is inconsistent (for example, a transaction not fully posted). On a healthy ledger they always match exactly — making this report a quick integrity check as well as a receivables tool. |

# **7\. What Data Appears on the Report**

The report reads only the Accounts Receivable subledger, and only the portion of each transaction that is still open. Understanding what raises and lowers A/R makes the numbers predictable.

## **7.1 Transactions that change A/R**

| Transaction type | Effect on A/R | Sign on report |
| :---- | :---: | :---: |
| **Invoice (to a customer)** | Increases | Positive (+) |
| **Payment received / deposit** | Decreases | Reduces the invoice |
| **Credit memo** | Decreases | Negative (–) |
| **Customer refund issued** | Adjusts | Depends on application |
| **Journal entry touching A/R** | Either | Per the entry |

## **7.2 Open balances only**

An invoice that has been paid in full disappears from the report — there is nothing left to collect. An invoice paid in part shows only its remaining open balance, aged from its original due date. This keeps the report focused on what is actually outstanding rather than the full transaction history.

## **7.3 Why some balances are negative**

Negative numbers are normal and meaningful on an A/R report. A negative balance means the flow has gone the other way — you effectively owe the customer, or they have paid ahead. The most common causes are:

* **Credit memos** that have not yet been applied against an invoice.

* **Overpayments** — the customer paid more than the invoice amount.

* **Prepayments / deposits / retainers** received before the matching invoice was issued.

* **Duplicate or early payments** awaiting a corresponding invoice.

When a negative sits in the same customer row as a positive invoice, the Total nets them. A persistently negative customer total is worth investigating — it often points to an unapplied credit or a payment that should be matched to an invoice, or a refund that is owed.

## **7.4 Accounting basis**

On an accrual basis, invoices are recognized when created, so they appear as soon as they exist. On a cash basis, the report behaves differently because revenue is recognized when collected. For receivables management, the accrual view is the standard choice, and it is the basis that reconciles cleanly to the Accounts Receivable line on the Balance Sheet.

# **8\. Filtering & Customization**

Everything about the report’s shape can be adjusted from the Customize panel. The most important settings are below; any combination can be saved as a named report for reuse.

| Setting | What it controls | Default / example |
| :---- | :---- | :---: |
| **Report period & as-of date** | The date basis the report is run on. “Today” ages everything as of the current date. | Today · 06/24/2026 |
| **Aging method** | Whether aging is measured as of the current date or the report date, and from the due date or transaction date. | Current / due date |
| **Days per aging period** | The width of each bucket in days. Set it to 15 for half-month bands, 30 for monthly. | 30 |
| **Number of periods** | How many discrete buckets appear before the final “and over” catch-all. | 4 |
| **Accounting method** | Accrual or cash basis recognition. | Accrual |
| **Customer filter** | Limit the report to one customer, a group, or all customers. | All |
| **A/R account** | If more than one receivables account exists, choose which to report on. | All A/R |
| **Columns & layout** | Show or hide columns, and switch between Compact and full layouts. | Standard |

| How the bucket math responds to settings Days per period and number of periods together define the column bands. With days \= 30 and periods \= 4 you get 1–30, 31–60, 61–90, then 91 and over. Switch days to 15 and the bands become 1–15, 16–30, 31–45, 46–60, then 61 and over. The aging engine simply re-applies the same “days past due” value against the new boundaries — no balance moves except as a consequence of the new ranges. |
| :---- |

# **9\. Data Representation & Formatting**

How the figures are displayed follows consistent conventions so the report reads cleanly at a glance.

| Convention | How it appears |
| :---- | :---- |
| **Number format** | Amounts use thousands separators and two decimal places (for example, 49,331.25). |
| **Currency** | The grand total carries the currency symbol (for example, $52,662.00); body figures are shown as plain numbers for readability. |
| **Negative values** | Shown with a leading minus sign (for example, –400.00). Depending on settings they may also appear in parentheses or in red. |
| **Zero / no balance** | Empty buckets are left blank rather than printed as 0.00, so the eye is drawn only to cells that carry a balance. |
| **Totals** | The customer Total column and the bottom Total row are emphasized; the grand total is bold and clearly separated. |
| **Sorting** | The Total column header includes a sort control to rank customers by balance size, largest or smallest first. |
| **Compact & zoom** | Compact tightens spacing; zoom scales the on-screen view. Both are display-only and never change the underlying numbers. |
| **Export & share** | The report can be refreshed, emailed, printed, or exported to spreadsheet or PDF for distribution. |

# **10\. Worked Example — Reading a Real Report**

The example below is an A/R Aging Summary for a company called Halo Axis, run as of June 24, 2026\. We will reproduce it exactly, then walk through every number so the logic in Sections 5 and 6 becomes concrete.

## **10.1 The report as displayed**

|  | Current | 1 – 30 | 31 – 60 | 61 – 90 | 91 and over | Total |
| :---- | ----: | ----: | ----: | ----: | ----: | ----: |
| **France** | 49,331.25 |  |  |  |  | 49,331.25 |
| **JumaTechs** | 3,330.75 |  |  |  |  | 3,330.75 |
| **TOTAL** | **52,662.00** |  |  |  |  | **$52,662.00** |

## **10.2 Reading each customer row**

**France.** A single open balance of 49,331.25 sits in Current, meaning every invoice to this customer is still within its payment terms — nothing is overdue. With no amount in any aging bucket, the row Total is simply 49,331.25. This is the largest balance on the report and makes up the bulk of what customers owe Halo Axis, but because it is current there is no collection action to take yet; the priority is simply to ensure it is paid on time as the due date approaches.

**JumaTechs.** A balance of 3,330.75, also entirely in Current. Like France, this customer is within terms with nothing overdue. It is a much smaller balance, so it contributes only modestly to the company-wide receivable.

| No overdue or negative balances in this snapshot Every figure on this particular report is current and positive — there are no overdue invoices, credit memos, or overpayments to interpret here. Had a customer been late, their balance would have appeared in 1–30, 31–60, 61–90, or 91 and over; had a credit been outstanding, it would have shown as a negative. Sections 5 and 7 explain exactly how those cases are placed and signed. |
| :---- |

## **10.3 Verifying the totals**

The bottom row and grand total can be reproduced exactly using the four-pass method:

| Figure | How it is reached |
| :---- | :---- |
| **Current column total** | 49,331.25 \+ 3,330.75 \= 52,662.00. |
| **1–30 … 91 and over** | No balances are overdue, so every other aging column is empty (zero). |
| **Grand total (across)** | 52,662.00 \+ 0 \= 52,662.00. |
| **Grand total (down)** | 49,331.25 \+ 3,330.75 \= 52,662.00. |
| **Cross-check** | Across and down both equal $52,662.00 — the report is internally consistent. |

| What this report is telling Halo Axis The entire $52,662.00 receivable is current: every customer is within their payment terms and nothing is overdue. This is the healthiest possible aging profile — no collections effort is required right now. The one feature worth noting is concentration: France alone accounts for roughly 94% of the outstanding receivable, so Halo Axis’s near-term incoming cash depends heavily on that single customer paying on schedule. Keeping an eye on France as its invoices come due is the only meaningful follow-up. |
| :---- |

# **11\. Reconciliation & Validation**

Because the report is just the A/R subledger re-presented by age, its grand total should tie back to the Accounts Receivable balance reported elsewhere in Pilucent.

## **11.1 The key relationship**

| A/R Aging Summary Total  \=  Accounts Receivable on the Balance Sheet |
| :---: |

When the A/R Aging Summary is run on an accrual basis for the same date as the Balance Sheet, the grand total should equal the Accounts Receivable line. Matching these two figures is a standard month-end control.

## **11.2 Common reasons they might differ**

* The two reports were run for different dates or on different accounting bases (cash vs. accrual).

* A journal entry posted directly to the A/R account without a customer attached, so it affects the Balance Sheet but not a customer row.

* More than one Accounts Receivable account exists and the aging report was filtered to only one of them.

* A transaction is mid-entry or not fully posted, leaving the subledger and general ledger temporarily out of step.

| Reconciliation tip If the numbers diverge, first confirm the date and accounting basis match on both reports. Next, look for A/R journal entries with no customer. These two checks resolve the large majority of A/R reconciliation differences. |
| :---- |

# **12\. Use Cases & Business Scenarios**

The same report supports several day-to-day and periodic decisions:

| Scenario | How the report helps |
| :---- | :---- |
| **Cash-flow forecasting** | Quantifies near-term and overdue incoming amounts so you can project collections and plan around them. |
| **Collections prioritization** | Working oldest-first (91 and over, then 61–90) focuses chase effort where the money is most at risk. |
| **Catching overdue invoices** | Surfaces anything that has slipped past its due date before it becomes a serious collection or bad-debt problem. |
| **Finding unapplied credits** | Negative balances flag credit memos and overpayments that should be applied or refunded. |
| **Customer credit decisions** | Aging behavior informs credit limits and payment terms — a customer who pays late may warrant tighter terms. |
| **Month-end close** | Provides the receivables figure to reconcile against the Balance Sheet and confirm the ledger is clean. |
| **Bad-debt & allowance review** | Long-overdue balances inform the allowance for doubtful accounts and any write-off decisions. |
| **Spotting concentration risk** | Shows when a single customer dominates receivables (as France does in the example), informing credit and cash-flow risk. |
| **Audit & review** | Demonstrates the completeness and valuation of receivables as of a chosen date. |

# **13\. Best Practices**

* Run the report on a regular cadence — weekly for active receivables, and always at month-end.

* Always note the run date. The same report on a different day will age balances differently.

* Act on overdue balances promptly — send reminders or statements before amounts drift into the oldest buckets.

* Investigate every negative customer total; apply or refund stale credits and unapplied payments.

* Reconcile the grand total to Accounts Receivable on the Balance Sheet at each close.

* Watch customer concentration — when one customer dominates the total, your incoming cash depends heavily on them.

* Drill from the Summary into the Detail report whenever a number needs explaining.

* Keep customer payment terms accurate — aging is only as reliable as the due dates behind it.

* Save a customized version once your columns and filters are set, so the layout is consistent every time.

# **14\. FAQ & Troubleshooting**

**Q.  A customer I expected is missing. Why?**

**A.**  Most likely that customer has no open balance — every invoice is fully paid, so there is nothing to age. The customer will reappear the moment a new unpaid invoice exists.

**Q.  Why is a balance negative?**

**A.**  A negative reflects a credit memo, overpayment, prepayment, or a payment not yet matched to an invoice. It means you effectively owe the customer for that portion. See Section 7.3.

**Q.  All of my balances are in Current. Is that good?**

**A.**  Yes — it means every customer is within their payment terms and nothing is overdue, which is the healthiest A/R picture. The Halo Axis example shows exactly this. The main thing to watch is customer concentration.

**Q.  Everything is in “91 and over.” What does that mean?**

**A.**  It means all open balances are more than 91 days past due relative to the aging date — a strong signal of collection risk and potential bad debt. It is not a report error; it is a prompt to prioritize collections on the oldest items.

**Q.  My report total doesn’t match the Balance Sheet.**

**A.**  Check that both use the same date and the same accounting basis, then look for A/R journal entries posted without a customer. See Section 11\.

**Q.  The numbers changed since yesterday and I didn’t enter anything.**

**A.**  Aging is measured against the run date. As time passes, balances drift into older buckets even with no new transactions.

**Q.  Can I change the column ranges?**

**A.**  Yes. Adjust “days per period” and “number of periods” in Customize. The buckets re-band automatically (Section 8).

**Q.  What’s the difference between Current and 1–30?**

**A.**  Current means not yet due as of the aging date. 1–30 means the due date has passed by up to a month. The dividing line is the due date itself.

# **15\. Glossary**

| Term | Definition |
| :---- | :---- |
| **Accounts Receivable (A/R)** | An asset representing money owed to your business by customers for goods or services already delivered. |
| **Aging** | The practice of classifying open balances by how long they have been outstanding. |
| **Aging bucket / period** | A defined range of days (for example, 31–60) used to group balances by age. |
| **Aging date / as-of date** | The single reference date against which every balance is aged. |
| **Aging method** | The setting that controls whether aging is measured from the due date or transaction date, and as of the current or report date. |
| **Allowance for doubtful accounts** | An estimate of receivables unlikely to be collected; long-overdue aging balances help inform it. |
| **Credit memo** | An amount owed back to a customer; it lowers A/R and can show as a negative balance. |
| **Current** | The bucket for balances not yet past due as of the aging date. |
| **Days past due** | Aging date minus due date; the value that determines a balance’s bucket. |
| **Due date** | The date an invoice is scheduled to be paid, often the invoice date plus payment terms. |
| **Invoice** | A recorded amount a customer owes you; creating one increases A/R. |
| **Open balance** | The unpaid or unapplied portion of a transaction; the only amount the report shows. |
| **Payment terms** | The agreed window for payment (for example, Net 30\) used to derive due dates. |

*End of document  ·  Pilucent — A/R Aging Summary Report Documentation  ·  v1.0*