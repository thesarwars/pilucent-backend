  
**BALANZIFY**

Accounting & Bookkeeping Platform

**Accounts Payable (A/P)**

**Aging Summary Report**

Product & Reporting Documentation

*Logic · Calculations · Filtering · Columns · Data Representation · Use Cases*

| Document | A/P Aging Summary Report — Functional Specification |
| :---- | :---- |
| **Module** | Reports → Payables → A/P Aging Summary |
| **Audience** | Business owners, bookkeepers, accountants, AP staff |
| **Version** | 1.0 |
| **Status** | Released |

**Table of Contents**

# **1\. Introduction & Overview**

The Accounts Payable (A/P) Aging Summary Report in Balanzify gives you a clear, single-screen picture of every unpaid amount your business owes to its vendors and suppliers — organized by how long each balance has been outstanding. Rather than scrolling through individual bills, you see one consolidated line per vendor, with that vendor’s open balance spread across a row of time-based “aging” columns.

In plain terms, the report turns a long list of bills into a short, prioritized snapshot. It is one of the most frequently used reports in any bookkeeping routine because it connects directly to cash: it tells you what you owe, to whom, and how urgent each payment has become.

## **1.1 What the report answers**

A single A/P Aging Summary is designed to answer three questions at a glance:

* **Who do we owe money to?** Each vendor with an open balance appears on its own row.

* **How much do we owe each of them?** The Total column shows the net balance per vendor, and the bottom Total row shows the company-wide payable.

* **How overdue is each amount?** The aging columns split every balance by the number of days it is past due, so genuinely late bills stand apart from amounts that are still within terms.

## **1.2 Who uses it**

| Role | Why they rely on it |
| :---- | :---- |
| **Business owner / founder** | Quick read on near-term cash obligations and which suppliers are waiting to be paid. |
| **Bookkeeper** | Daily and month-end check that payables are accurate, and that nothing has slipped overdue unnoticed. |
| **Accountant / Controller** | Reconciles the report total to the Accounts Payable balance on the Balance Sheet and reviews aging health. |
| **Accounts Payable clerk** | Works the list from oldest to newest, prioritizing payments and chasing down billing discrepancies. |
| **Auditor / Reviewer** | Tests the completeness and valuation of liabilities as of a specific date. |

## **1.3 Where it sits in the payables workflow**

Every time you enter a bill, apply a vendor credit, or record a bill payment, Balanzify updates the underlying Accounts Payable ledger. The A/P Aging Summary is the reporting lens placed over that ledger. It does not create or change any data — it reads the current open balances and re-presents them by age. Because of this, the report is always only as accurate as the bills, credits, and payments behind it.

| Summary vs. Detail Balanzify offers two related reports. The A/P Aging Summary (this document) shows one rolled-up row per vendor. The A/P Aging Detail report breaks the same balances down into the individual transactions — each bill, its date, due date, and open amount. Whenever you need to see what makes up a number on the Summary, drill into the Detail. |
| :---- |

# **2\. Key Concepts & Terminology**

A few core ideas drive everything in this report. Getting comfortable with them makes the calculations and settings that follow easy to read.

| Term | Meaning in Balanzify |
| :---- | :---- |
| **Accounts Payable (A/P)** | The money your business owes to vendors for goods or services received but not yet paid for. It is a liability. |
| **Bill** | A transaction recording an obligation to pay a vendor. Entering a bill increases A/P. |
| **Bill payment** | A transaction that settles all or part of a bill. It decreases A/P. A bill can be paid in several installments. |
| **Vendor credit** | An amount a vendor owes back to you (a return, allowance, or correction). It decreases A/P and can appear as a negative balance until applied. |
| **Open balance** | The portion of a transaction still unpaid or unapplied. Only open balances appear on the report; fully settled items drop off. |
| **Due date** | The date a bill is scheduled to be paid, usually derived from the bill date plus the vendor’s payment terms (for example, Net 30). |
| **Transaction date** | The date written on the bill itself — typically when the goods or services were billed. |
| **Aging date (as-of date)** | The reference date the report uses to measure how old each balance is. Everything is aged relative to this single date. |
| **Aging bucket / period** | A range of days (for example, 31–60) into which a balance is placed based on how overdue it is. |

# **3\. Anatomy of the Report**

The screen is made up of a small control strip, a report header, the data grid, and a footer. Knowing each region makes the rest of this document easier to follow.

## **3.1 The control strip**

Running across the top of the report are the controls used to shape and share it:

* **Report period selector —** chooses the date window for the report (for example, All Dates, This Month, or a custom range).

* **Customize —** opens the full settings panel: aging method, days per period, number of periods, filters, columns, and header/footer options.

* **Save As —** stores your customized version as a reusable saved report so you do not have to re-set the options each time.

* **Refresh, Email, Print, Export —** regenerate the figures, send the report, print it, or export it to a spreadsheet or PDF.

* **Compact and zoom —** toggle a denser layout and scale the on-screen size (for example, 100%). These affect display only, never the numbers.

## **3.2 The report header**

Centered above the grid, the header identifies exactly what you are looking at:

* **Company name** — the business the report belongs to.

* **Report title** — “A/P Aging Summary Report.”

* **Date basis** — the selected report period (for example, “All Dates”).

## **3.3 The data grid**

The body is a simple matrix. Each row is a vendor; each column is an aging bucket, with a Total column on the right. The bottom row totals every column down the page. A sort control on the Total column header lets you rank vendors by the size of their balance.

## **3.4 The footer**

Below the grid, Balanzify stamps the exact date and time the report was generated, along with the time zone. This timestamp matters: because aging is measured against a reference date, two copies of the same report run on different days can legitimately show different numbers. There is also an option to attach a note for context.

# **4\. Columns Explained**

With the default settings (30 days per period and four periods), the report shows the following columns from left to right. The vendor name occupies the first, unlabeled column.

| Column | What it represents | Days past due |
| :---- | :---- | :---: |
| **Vendor** | The supplier the balance is owed to. One row per vendor with any open balance. | — |
| **Current** | Balances that are not yet overdue — still within their payment terms as of the aging date. | 0 or not yet due |
| **1 – 30** | Balances that became overdue within the last month. | 1 to 30 days |
| **31 – 60** | Balances overdue by one to two months. | 31 to 60 days |
| **61 – 90** | Balances overdue by two to three months. | 61 to 90 days |
| **91 and over** | Long-overdue balances; the catch-all for anything older than the last defined period. | 91+ days |
| **Total** | The vendor’s net open balance — the sum of all aging columns on that row. | All ages combined |

| About the column count and width The exact number of aging columns is configurable. The default of four 30-day periods produces Current, 1–30, 31–60, 61–90, and 91 and over. Changing “days per period” or “number of periods” in Customize re-labels and re-bands these columns automatically (see Section 8). |
| :---- |

# **5\. The Aging Logic (Core Engine)**

Aging is the heart of this report. Strip everything else away and the question is simple: for each open balance, how many days late is it, and therefore which column does it belong in?

## **5.1 Step one — establish the aging date**

Every balance is measured against a single reference date, called the aging date. By default this is the end of the selected report period. When the period is “All Dates,” the aging date is effectively today — the day you run the report. (The aging method setting, covered in Section 8, lets you base it on the current date or the report date explicitly.) This is why the footer timestamp is important: it records the moment that drove the aging.

## **5.2 Step two — measure days outstanding**

For each open transaction, Balanzify calculates how many days have elapsed between its due date and the aging date:

| Days Past Due  \=  Aging Date  −  Due Date |
| :---: |

A positive result means the balance is overdue by that many days. A result of zero or below means it is *not yet due* and is therefore considered current.

| Which date drives aging: due date vs. transaction date By default, Balanzify ages each balance from its due date — the most common and intuitive choice, because a bill is only “late” once its due date has passed. If you prefer, the aging method can instead measure from the transaction (bill) date, which ages everything from when it was billed regardless of terms. The bucket boundaries below work identically either way; only the date you subtract changes. |
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

* **A bill due July 5, 2026** → due date is in the future, days past due is negative → **Current**.

* **A bill due June 10, 2026** → 14 days past due → **1 – 30**.

* **A bill due April 20, 2026** → 65 days past due → **61 – 90**.

* **A bill due January 2, 2026** → 173 days past due → **91 and over**.

| Each transaction ages on its own A vendor can appear in more than one column at once. If you owe a vendor on an old bill and also hold a recent credit from them, the bill and the credit are aged separately and land in different columns. Only the Total column nets them together. You will see exactly this in the worked example in Section 10\. |
| :---- |

# **6\. Calculation Methodology**

The report is built in four passes: per transaction, per vendor, per column, and finally the grand total. Each pass is a straightforward sum, which is what makes the report fast and easy to verify by hand.

## **6.1 Pass 1 — per transaction**

1. Take the open balance of every unpaid bill, unapplied vendor credit, and any A/P journal entry.

2. Compute days past due for each using the formula in Section 5.2.

3. Drop each open balance into its matching aging bucket. Credits and overpayments carry a negative sign.

## **6.2 Pass 2 — per vendor (each row)**

All of a vendor’s bucketed amounts are grouped onto a single row, then summed across to produce the Total for that vendor:

| Vendor Total  \=  Current \+ (1–30) \+ (31–60) \+ (61–90) \+ (91 and over) |
| :---: |

## **6.3 Pass 3 — per column (the bottom row)**

Each aging column is summed straight down the page across all vendors, producing the column totals on the Total row.

| Column Total  \=  Σ (that column’s amount for every vendor) |
| :---: |

## **6.4 Pass 4 — the grand total**

The bottom-right figure is the company-wide net payable. It can be reached two independent ways, and the two must agree — a built-in cross-check:

* **Across the bottom row:** sum of all column totals.

* **Down the Total column:** sum of all vendor totals.

| Σ Column Totals   \=   Σ Vendor Totals   \=   Grand Total |
| ----- |
| **A handy validation** If the two ways of reaching the grand total ever disagree, the data behind the report is inconsistent (for example, a transaction not fully posted). On a healthy ledger they always match exactly — making this report a quick integrity check as well as a payables tool. |

# **7\. What Data Appears on the Report**

The report reads only the Accounts Payable subledger, and only the portion of each transaction that is still open. Understanding what raises and lowers A/P makes the numbers predictable.

## **7.1 Transactions that change A/P**

| Transaction type | Effect on A/P | Sign on report |
| :---- | :---: | :---: |
| **Bill (vendor invoice)** | Increases | Positive (+) |
| **Bill payment / check** | Decreases | Reduces the bill |
| **Vendor credit / credit memo** | Decreases | Negative (–) |
| **Vendor refund received** | Adjusts | Depends on application |
| **Journal entry touching A/P** | Either | Per the entry |

## **7.2 Open balances only**

A bill that has been paid in full disappears from the report — there is nothing left to owe. A bill paid in part shows only its remaining open balance, aged from its original due date. This keeps the report focused on what is actually outstanding rather than the full transaction history.

## **7.3 Why some balances are negative**

Negative numbers are normal and meaningful on an A/P report. A negative balance means the flow has gone the other way — the vendor effectively owes you, or you have paid ahead. The most common causes are:

* **Vendor credits** that have not yet been applied against a bill.

* **Overpayments** — you paid more than the bill amount.

* **Prepayments / deposits** recorded before the matching bill arrived.

* **Duplicate or early payments** awaiting a corresponding bill.

When a negative sits in the same vendor row as a positive bill, the Total nets them. A persistently negative vendor total is worth investigating — it often points to an unapplied credit or a payment that should be matched to a bill.

## **7.4 Accounting basis**

On an accrual basis, bills are recognized when entered, so they appear as soon as they exist. On a cash basis, the report behaves differently because liabilities are recognized when paid. For payables management, the accrual view is the standard choice, and it is the basis that reconciles cleanly to the Accounts Payable line on the Balance Sheet.

# **8\. Filtering & Customization**

Everything about the report’s shape can be adjusted from the Customize panel. The most important settings are below; any combination can be saved as a named report for reuse.

| Setting | What it controls | Default |
| :---- | :---- | :---: |
| **Report period** | The date window of transactions included. “All Dates” includes everything. | All Dates |
| **Aging method** | Whether aging is measured as of the current date or the report date, and from the due date or transaction date. | Current / due date |
| **Days per aging period** | The width of each bucket in days. Set it to 15 for half-month bands, 30 for monthly. | 30 |
| **Number of periods** | How many discrete buckets appear before the final “and over” catch-all. | 4 |
| **Accounting method** | Accrual or cash basis recognition. | Accrual |
| **Vendor filter** | Limit the report to one vendor, a group, or all vendors. | All |
| **A/P account** | If more than one payables account exists, choose which to report on. | All A/P |
| **Columns & layout** | Show or hide columns, and switch between Compact and full layouts. | Standard |

| How the bucket math responds to settings Days per period and number of periods together define the column bands. With days \= 30 and periods \= 4 you get 1–30, 31–60, 61–90, then 91 and over. Switch days to 15 and the bands become 1–15, 16–30, 31–45, 46–60, then 61 and over. The aging engine simply re-applies the same “days past due” value against the new boundaries — no balance moves except as a consequence of the new ranges. |
| :---- |

# **9\. Data Representation & Formatting**

How the figures are displayed follows consistent conventions so the report reads cleanly at a glance.

| Convention | How it appears |
| :---- | :---- |
| **Number format** | Amounts use thousands separators and two decimal places (for example, 395,790.00). |
| **Currency** | The grand total carries the currency symbol (for example, $400,840.00); body figures are shown as plain numbers for readability. |
| **Negative values** | Shown with a leading minus sign (for example, –400.00). Depending on settings they may also appear in parentheses or in red. |
| **Zero / no balance** | Empty buckets are left blank rather than printed as 0.00, so the eye is drawn only to cells that carry a balance. |
| **Totals** | The vendor Total column and the bottom Total row are emphasized; the grand total is bold and clearly separated. |
| **Sorting** | The Total column header includes a sort control to rank vendors by balance size, largest or smallest first. |
| **Compact & zoom** | Compact tightens spacing; zoom scales the on-screen view. Both are display-only and never change the underlying numbers. |
| **Export & share** | The report can be refreshed, emailed, printed, or exported to spreadsheet or PDF for distribution. |

# **10\. Worked Example — Reading a Real Report**

The example below is an A/P Aging Summary for a company called Halo Axis, run for All Dates as of June 24, 2026\. We will reproduce it exactly, then walk through every number so the logic in Sections 5 and 6 becomes concrete.

## **10.1 The report as displayed**

|  | Current | 1 – 30 | 31 – 60 | 61 – 90 | 91 and over | Total |
| :---- | ----: | ----: | ----: | ----: | ----: | ----: |
| **Binary Burst** |  |  |  |  | 9,350.00 | 9,350.00 |
| **Kaniz** |  |  |  | 1,200.00 | –400.00 | 800.00 |
| **Ragib** |  |  |  |  | –5,100.00 | –5,100.00 |
| **Unimart** |  |  |  |  | 395,790.00 | 395,790.00 |
| **TOTAL** |  |  |  | **1,200.00** | **399,640.00** | **$400,840.00** |

## **10.2 Reading each vendor row**

**Binary Burst.** A single open balance of 9,350.00 sits in 91 and over, meaning this bill is more than 91 days past due. With nothing in any other bucket, the row Total is simply 9,350.00. This is the report’s clearest “please pay me” signal — a meaningful amount that is badly overdue.

**Kaniz.** This vendor shows two amounts in two different buckets: a 1,200.00 bill in 61–90 and a –400.00 credit in 91 and over. They are aged independently — the bill is two-to-three months overdue, while the credit is older still. The Total column nets them: 1,200.00 \+ (–400.00) \= **800.00**. So the company genuinely owes Kaniz 800.00 net, but the report preserves the detail that part of the balance is an old credit waiting to be applied.

**Ragib.** The only figure is –5,100.00 in 91 and over, and the Total is the same. A wholly negative vendor means Halo Axis does not owe Ragib anything — instead there is a 5,100.00 credit or overpayment on file. Because it is sitting in the oldest bucket, it has been outstanding a long time and should probably be applied to a bill or refunded.

**Unimart.** A large 395,790.00 balance, again entirely in 91 and over. This one vendor dominates the company’s payables and is long overdue, so it is the single biggest driver of the grand total and the first place a reviewer’s eye should go.

## **10.3 Verifying the totals**

The bottom row and grand total can be reproduced exactly using the four-pass method:

| Figure | How it is reached |
| :---- | :---- |
| **61 – 90 column total** | Only Kaniz has a 61–90 amount → 1,200.00. |
| **91 and over column total** | 9,350.00 \+ (–400.00) \+ (–5,100.00) \+ 395,790.00 \= 399,640.00. |
| **Grand total (across)** | 1,200.00 \+ 399,640.00 \= 400,840.00. |
| **Grand total (down)** | 9,350.00 \+ 800.00 \+ (–5,100.00) \+ 395,790.00 \= 400,840.00. |
| **Cross-check** | Across and down both equal $400,840.00 — the report is internally consistent. |

| What this report is telling Halo Axis Almost the entire $400,840.00 payable is more than 91 days overdue, and one vendor (Unimart) accounts for the vast majority of it. There are no current or near-term balances at all. In practice this is a red flag: it suggests bills are not being paid on schedule, and it would prompt an immediate review of the oldest items — especially Unimart and Binary Burst — plus a clean-up of the Ragib and Kaniz credits. |
| :---- |

# **11\. Reconciliation & Validation**

Because the report is just the A/P subledger re-presented by age, its grand total should tie back to the Accounts Payable balance reported elsewhere in Balanzify.

## **11.1 The key relationship**

| A/P Aging Summary Total  \=  Accounts Payable on the Balance Sheet |
| :---: |

When the A/P Aging Summary is run on an accrual basis for the same date as the Balance Sheet, the grand total should equal the Accounts Payable line. Matching these two figures is a standard month-end control.

## **11.2 Common reasons they might differ**

* The two reports were run for different dates or on different accounting bases (cash vs. accrual).

* A journal entry posted directly to the A/P account without a vendor attached, so it affects the Balance Sheet but not a vendor row.

* More than one Accounts Payable account exists and the aging report was filtered to only one of them.

* A transaction is mid-entry or not fully posted, leaving the subledger and general ledger temporarily out of step.

| Reconciliation tip If the numbers diverge, first confirm the date and accounting basis match on both reports. Next, look for A/P journal entries with no vendor. These two checks resolve the large majority of A/P reconciliation differences. |
| :---- |

# **12\. Use Cases & Business Scenarios**

The same report supports several day-to-day and periodic decisions:

| Scenario | How the report helps |
| :---- | :---- |
| **Cash-flow planning** | Quantifies near-term and overdue obligations so you can plan outgoing cash and avoid surprises. |
| **Payment prioritization** | Working oldest-first (91 and over, then 61–90) protects key vendor relationships and avoids late fees. |
| **Catching overdue bills** | Surfaces anything that has slipped past its due date before it becomes a relationship or credit problem. |
| **Finding unapplied credits** | Negative balances flag vendor credits and overpayments that should be applied or refunded. |
| **Month-end close** | Provides the payables figure to reconcile against the Balance Sheet and confirm the ledger is clean. |
| **Vendor negotiations** | A clear aging picture supports conversations about terms, early-payment discounts, or disputed charges. |
| **Audit & review** | Demonstrates the completeness and valuation of liabilities as of a chosen date. |
| **Spotting concentration risk** | Shows when a single vendor dominates payables (as Unimart does in the example), informing risk and terms. |

# **13\. Best Practices**

* Run the report on a regular cadence — weekly for active payables, and always at month-end.

* Always note the run date. The same report on a different day will age balances differently.

* Investigate every negative vendor total; apply or clear stale credits promptly.

* Reconcile the grand total to Accounts Payable on the Balance Sheet at each close.

* Drill from the Summary into the Detail report whenever a number needs explaining.

* Keep vendor payment terms accurate — aging is only as reliable as the due dates behind it.

* Save a customized version once your columns and filters are set, so the layout is consistent every time.

# **14\. FAQ & Troubleshooting**

**Q.  A vendor I expected is missing. Why?**

**A.**  Most likely that vendor has no open balance — every bill is fully paid, so there is nothing to age. The vendor will reappear the moment a new unpaid bill exists.

**Q.  Why is a balance negative?**

**A.**  A negative reflects a vendor credit, overpayment, prepayment, or a payment not yet matched to a bill. It means the vendor effectively owes you for that portion. See Section 7.3.

**Q.  Everything is in “91 and over.” Is that a bug?**

**A.**  No. It simply means all open balances are more than 91 days past due relative to the aging date — a sign that bills are old, not that the report is wrong. The Halo Axis example shows exactly this.

**Q.  My report total doesn’t match the Balance Sheet.**

**A.**  Check that both use the same date and the same accounting basis, then look for A/P journal entries posted without a vendor. See Section 11\.

**Q.  The numbers changed since yesterday and I didn’t enter anything.**

**A.**  Aging is measured against the run date. As time passes, balances drift into older buckets even with no new transactions.

**Q.  Can I change the column ranges?**

**A.**  Yes. Adjust “days per period” and “number of periods” in Customize. The buckets re-band automatically (Section 8).

**Q.  What’s the difference between Current and 1–30?**

**A.**  Current means not yet due as of the aging date. 1–30 means the due date has passed by up to a month. The dividing line is the due date itself.

# **15\. Glossary**

| Term | Definition |
| :---- | :---- |
| **Accounts Payable (A/P)** | A liability representing money owed to vendors for goods or services already received. |
| **Aging** | The practice of classifying open balances by how long they have been outstanding. |
| **Aging bucket / period** | A defined range of days (for example, 31–60) used to group balances by age. |
| **Aging date / as-of date** | The single reference date against which every balance is aged. |
| **Aging method** | The setting that controls whether aging is measured from the due date or transaction date, and as of the current or report date. |
| **Bill** | A recorded obligation to pay a vendor; entering one increases A/P. |
| **Current** | The bucket for balances not yet past due as of the aging date. |
| **Days past due** | Aging date minus due date; the value that determines a balance’s bucket. |
| **Due date** | The date a bill is scheduled to be paid, often the bill date plus payment terms. |
| **Open balance** | The unpaid or unapplied portion of a transaction; the only amount the report shows. |
| **Payment terms** | The agreed window for payment (for example, Net 30\) used to derive due dates. |
| **Vendor credit** | An amount owed back by a vendor; it lowers A/P and can show as a negative balance. |

*End of document  ·  Balanzify — A/P Aging Summary Report Documentation  ·  v1.0*