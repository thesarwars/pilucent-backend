

| PILUCENT   ·   PRODUCT DOCUMENTATION A/P Aging Detail Report Logic · Calculations · Filtering · Columns · Data Representation · Use Cases |
| :---- |

This guide explains exactly how Pilucent builds the Accounts Payable (A/P) Aging Detail Report. It walks through every column, the formulas behind each figure, how transactions are sorted into aging buckets, the filtering and customization options available to you, and the day-to-day decisions the report is designed to support. It is written for business owners, bookkeepers, accountants, and anyone on the finance team who needs a clear picture of what the company owes and when it is due.

**Module:**  Accounts Payable · Reporting        **Report type:**  Detail        **Version:**  1.0

Audience: Finance, Accounting & Bookkeeping teams

Last updated: June 2026

**Contents**

**1  Introduction**3

1.1  About this guide3

1.2  What the A/P Aging Detail Report is3

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

5.4  Credits and items without a due date6

**6  Calculations**7

**7  Report period and date settings**7

**8  Filtering and customization**8

8.1  The Customize panel8

8.2  Columns you can add8

**9  Data representation and formatting**8

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

Pilucent reports are most useful when you know precisely what each number means and where it comes from. This document removes the guesswork from the A/P Aging Detail Report. By the end of it you should be able to read any line on the report with confidence, reproduce every total by hand, and adjust the report so it answers the specific question in front of you — whether that is “who do we owe right now?”, “what is dangerously overdue?”, or “does this balance tie out at month-end?”

## **1.2  What the A/P Aging Detail Report is**

**Accounts Payable (A/P)** is the money your business owes to vendors and suppliers for goods or services you have received but have not yet paid for. The A/P Aging Detail Report takes every **open** (unpaid) payable in your books and lists it transaction by transaction, organized by how overdue it is. Instead of a single lump sum, you see each individual bill and vendor credit: who it is owed to, when it was due, how many days it has been outstanding, and how much is still open.

The word **Detail** is the important part. Pilucent offers two closely related reports built from the same data:

* **A/P Aging Summary —** collapses everything into one row per vendor, spread across a set of aging columns. It answers “how much, and how old, per vendor.”

* **A/P Aging Detail (this report) —** expands those balances into every underlying transaction. It answers “exactly which bills and credits make up that balance.”

Use the Summary for a quick health check and the Detail when you need to act on, verify, or explain a specific number.

## **1.3  Why it matters**

* It tells you what you owe and when, so you can plan payments and protect your cash position.

* It surfaces overdue bills before they turn into late fees, interest, or strained vendor relationships.

* It lets you prioritize — pay the oldest or most critical items first.

* It exposes unused vendor credits you could be applying instead of paying cash.

* It supports month-end close: the report’s total open balance should reconcile to the Accounts Payable balance on your Balance Sheet.

| At a glance Report family — Detail — one row per transaction. Source — Your Accounts Payable account(s). Shows — Open (unpaid) bills and unapplied vendor credits only — fully settled items drop off. Default grouping — Aging bands — Current, 1–30, 31–60, 61–90, and 91+ days past due. Default sort — Due date, oldest first. Signs — Bills are positive; vendor credits are negative. Key figure — Open balance \= what you still owe (or still hold as credit) today. |
| :---- |

# **2  Key concepts and terminology**

A handful of terms appear throughout the report and this guide. Skim these once and the rest of the document reads easily.

| Term | What it means |
| :---- | :---- |
| **Accounts Payable (A/P)** | Money your business owes to vendors for goods or services received but not yet paid. |
| **Payable** | A single amount you owe — most often a bill. |
| **Aging** | Sorting open payables by how long they have been outstanding, i.e. how overdue they are. |
| **Aging bucket (interval)** | A date range used to group items, such as “1–30 days past due.” |
| **Bill** | A request for payment from a vendor. It increases A/P (positive). |
| **Vendor credit** | A credit a vendor issues you (a return, refund, or adjustment) that reduces what you owe. Shown as a negative amount. |
| **Due date** | The date a bill must be paid, set by the payment terms (e.g. Net 30). |
| **Past due (days)** | How many days an item is overdue, measured from its due date to the report date. |
| **Open balance** | The unpaid (or unapplied) portion still outstanding on a transaction. |
| **As-of / report date** | The point in time the report is calculated for — the date aging is measured against. |
| **Report period** | The date setting that controls which transactions are included and the as-of date used. |

# **3  How to read the report**

## **3.1  The regions of the report**

From top to bottom, the report is organized into a few predictable regions. Knowing what each one does makes the whole report easy to scan.

| Region | Where it is | What it does |
| :---- | :---- | :---- |
| **Report title** | Top, centered | Names the report — “A/P Aging Detail Report.” |
| **Report period** | Top-left control | Sets the date range and as-of date for the whole report (see Section 7). |
| **Toolbar** | Top-right icons | View/zoom, refresh, email, print, and export (spreadsheet or PDF). |
| **Column headers** | Below the title | Label each column; the small arrows sort rows within each band. |
| **Aging band header** | Shaded row with a count | Starts a group, e.g. “91 or more days past due (9).” The number is the count of lines in that band. |
| **Detail rows** | Under each band | One transaction per line — the heart of the report. |
| **Band subtotal** | “Total for …” row | Sums Amount and Open balance for that band. |
| **Grand total** | “TOTAL” row at the bottom | Sums every band into a single A/P figure. |

## **3.2  The aging bands**

Every open item is filed into exactly one aging band based on how overdue it is. Reading the bands from top to bottom takes you from the most overdue items to the least (or the reverse, depending on your sort). Bands with no qualifying transactions are simply omitted — that is why the sample report shows only the “91 or more” and “61 – 90” bands and not the others.

# **4  Column reference**

Below is every default column on the report, what it shows, and where its value comes from. You can add, remove, and reorder columns under Customize (Section 8).

| Column | What it shows | Where it comes from / how it is calculated |
| :---- | :---- | :---- |
| **Date** | The date the transaction was recorded. | Taken straight from the transaction — the bill date or the credit date. Also used as the aging basis when a line has no due date. |
| **Transaction type** | The kind of payable — usually Bill or Vendor Credit. | Tells you whether the line increases what you owe (Bill, positive) or reduces it (Vendor Credit, negative). |
| **Num** | The reference or document number. | Pulled from the transaction’s reference field. Blank if none was entered (common for vendor credits). |
| **Vendor display name** | The vendor the payable is owed to. | The name as it appears in your vendor list. Group or filter by this to see one supplier at a time. |
| **Store full name** | The store, location, or class assigned. | Only meaningful if you track multiple locations. Blank when no location is assigned. |
| **Due date** | When payment is due to the vendor. | Bill date \+ payment terms (e.g. Net 30). This is the date the aging clock counts from. Vendor credits usually have none. |
| **Past due** | Days overdue as of the report date. | Report (as-of) date − Due date. Zero or blank means not yet due. Determines the aging band. |
| **Amount** | The original, full value of the transaction. | Bills positive, vendor credits negative. Does not change as payments are made. |
| **Open balance** | What is still outstanding right now. | Amount − payments/credits already applied. Equals Amount when nothing has been settled. This is the real “what you owe today.” |

# **5  Aging logic: how items land in a bucket**

## **5.1  The aging date basis**

The report ages each open item by comparing a reference date — the **as-of date** — to the item’s **due date**. The number of whole days between them is the item’s days past due. When the Report period is set to **All Dates**, the as-of date is simply today, so the report shows what is overdue as of the moment you run it.

| days\_past\_due  \=  as\_of\_date  −  due\_date   • result ≤ 0   → not yet due (belongs in “Current”); Past due shows 0 / blank • result ≥ 1   → overdue by that many days |
| :---- |

## **5.2  The default buckets**

Pilucent files items into these standard bands. Reading them as a ladder, “Current” sits at the top (nothing overdue) and each step down is another period of lateness.

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

Vendor credits reduce what you owe and normally carry no payment due date. When a transaction has no due date, Pilucent ages it by its transaction date instead. That is why, in the sample report, the vendor credits dated in 2025 appear inside the “91 or more days past due” band even though their Due date and Past due columns are blank — measured from their own date, they are well over 91 days old.

# **6  Calculations**

Every figure on the report can be reproduced with a few simple rules.

**6.1  Past due (days).**  Past due \= as-of date − Due date. A negative or zero result means the item is not yet due, so the line lands in Current and Past due reads 0 (or blank). A positive result is the number of days late, and it decides the aging band.

**6.2  Open balance.**  Open balance \= Amount − (payments or credits already applied to that transaction). When nothing has been paid or applied, Open balance equals Amount. In the sample, the Unimart vendor credit shows an Amount of −1,360.00 but an Open balance of −210.00 — meaning 1,150.00 of that credit has already been applied against bills, leaving 210.00 still available to use.

**6.3  Sign conventions.**  Bills are positive because they increase A/P. Vendor credits are negative because they reduce it. Bill payments, once applied, lower the open balance of the bills they pay; a bill that is paid in full has a zero open balance and therefore drops off the report entirely. The report only ever lists transactions whose open balance is not zero as of the report date.

**6.4  Subtotals and the grand total.**  Each band shows a “Total for …” row that sums the Amount and Open balance columns for the lines in that band. Because credits are negative, a band’s subtotal naturally nets bills against credits. The “TOTAL” row at the bottom sums all bands into your overall A/P position.

# **7  Report period and date settings**

The Report period control (top-left) drives the dates the report uses. The dropdown offers a standard set of ready-made ranges plus a custom option:

| Option | What it does |
| :---- | :---- |
| **All Dates** | Includes every open payable and ages it as of the current date. The most common choice for a true “what do we owe right now” view. |
| **Custom dates** | You pick a specific From/To range and as-of date — useful for historical or point-in-time aging. |
| **Today** | Limits to today and ages as of today. |
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

* **Filter —** narrow the report by Vendor, Transaction type, Store/Location, or A/P account when you keep more than one.

* **Header / Footer —** control the company name, report title, the prepared date/time, and page numbers shown on the printed report.

Once a report looks the way you want, use Save As to keep it as a custom report you can reopen with one click.

## **8.2  Columns you can add**

Beyond the defaults, you can surface extra columns when you need more context. Common additions include:

* Account (the expense or asset account the bill posts to)

* Memo / Description

* Terms (e.g. Net 15, Net 30\)

* Currency and exchange rate (for multi-currency books)

* Created date, Last modified, and Last modified by (for audit trails)

# **9  Data representation and formatting**

How the report displays its data is just as important as the numbers themselves:

* **Grouping —** rows are grouped into aging bands; each band carries a header (with a line count) and a subtotal.

* **Sorting —** the arrows in each column header sort rows within each band. The default is Due date, ascending — so within a band, dated bills appear oldest-first and items without a due date (such as credits) follow.

* **Signs and emphasis —** bills are positive and credits negative; via number format, negatives can be shown in red or wrapped in parentheses. Subtotals and the grand total are bold and separated by a rule line.

* **Collapse / expand —** the chevron beside each band header collapses that band down to just its subtotal, which is handy when you only care about totals.

* **Zoom and density —** the “Normal | 100%” control adjusts zoom and the on-screen density.

* **Share and export —** the toolbar lets you refresh, email, print, or export the report to a spreadsheet or PDF, preserving the grouping and totals.

# **10  Transaction types included**

Any transaction that posts to your Accounts Payable account and still has an open balance can appear. The most common are:

* **Bill —** a payable you owe a vendor. Positive; carries a due date based on its terms.

* **Vendor Credit —** a credit from a vendor that offsets what you owe. Negative; usually no due date, so it ages by its own date.

* **Bill Payment —** a payment applied to one or more bills. It reduces the open balance of those bills; if it carries no remaining open balance it nets away and the paid bill drops off the report.

Journal entries and other transactions that post directly to the A/P account with an open balance can also surface here. Purchase orders do not — they are commitments, not posted payables, and only affect A/P once turned into a bill.

# **11  Worked example: the sample report**

## **11.1  The data**

Here is a faithful recreation of the sample A/P Aging Detail Report. It is aged as of the current date — in this example, June 24, 2026 — which is why the bill due 05/26/2025 shows 394 days past due.

| Date | Transaction type | Num | Vendor display name | Store full name | Due date | Past due | Amount | Open balance |
| :---- | :---- | :---- | :---- | :---- | :---- | ----: | ----: | ----: |
| **91 or more days past due (9)** |  |  |  |  |  |  |  |  |
| 05/26/2025 | Bill |  | Binary Burst |  | 05/26/2025 | 394 | 12,000.00 | 12,000.00 |
| 06/25/2025 | Bill |  | Unimart |  | 07/10/2025 | 349 | 400,000.00 | 400,000.00 |
| 04/23/2025 | Vendor Credit |  | Unimart |  |  |  | \-1,360.00 | \-210.00 |
| 06/16/2025 | Vendor Credit |  | Kaniz |  |  |  | \-400.00 | \-400.00 |
| 06/16/2025 | Vendor Credit |  | Binary Burst |  |  |  | \-2,250.00 | \-2,250.00 |
| 06/16/2025 | Vendor Credit |  | Ragib |  |  |  | \-4,100.00 | \-4,100.00 |
| 06/25/2025 | Vendor Credit |  | Binary Burst |  |  |  | \-400.00 | \-400.00 |
| 06/25/2025 | Vendor Credit |  | Ragib |  |  |  | \-1,000.00 | \-1,000.00 |
| 06/25/2025 | Vendor Credit |  | Unimart |  |  |  | \-4,000.00 | \-4,000.00 |
| **Total for 91 or more days past due** |  |  |  |  |  |  | **$398,490.00** | **$399,640.00** |
| **61 \- 90 days past due (1)** |  |  |  |  |  |  |  |  |
| 04/14/2026 | Bill |  | Kaniz |  | 04/14/2026 | 71 | 1,200.00 | 1,200.00 |
| **Total for 61 \- 90 days past due** |  |  |  |  |  |  | **$1,200.00** | **$1,200.00** |
| **TOTAL** |  |  |  |  |  |  | **$399,690.00** | **$400,840.00** |

## **11.2  How the key numbers are derived**

**Past due.** The Binary Burst bill is due 05/26/2025. Counting forward to the as-of date of 06/24/2026 gives 394 days, so it sits firmly in the 91+ band. The Unimart bill is dated 06/25/2025 with Net-15 terms, putting its due date at 07/10/2025 — 349 days before the as-of date. The Kaniz bill is due 04/14/2026; 16 days remain in April, plus 31 in May, plus 24 in June, equals 71 days late, landing it in the 61–90 band.

**Band subtotal (91+).** Add the two bills and subtract the seven credits:

| Amount        \=  12,000 \+ 400,000                  − (1,360 \+ 400 \+ 2,250 \+ 4,100 \+ 400 \+ 1,000 \+ 4,000)               \=  412,000 − 13,510   \=   398,490.00   Open balance  \=  12,000 \+ 400,000                  − (  210 \+ 400 \+ 2,250 \+ 4,100 \+ 400 \+ 1,000 \+ 4,000)               \=  412,000 − 12,360   \=   399,640.00 |
| :---- |

Both figures match the “Total for 91 or more days past due” row exactly. The 61–90 band holds a single 1,200.00 bill, so its subtotal equals that line.

**Grand total.** Adding the bands together gives Amount 398,490.00 \+ 1,200.00 \= 399,690.00 and Open balance 399,640.00 \+ 1,200.00 \= 400,840.00 — the figures shown on the TOTAL row.

## **11.3  A quick reconciliation check**

Notice the two grand totals differ: Amount is 399,690.00 but Open balance is 400,840.00 — a gap of exactly 1,150.00. That gap is not an error; it is the part of the Unimart credit that has already been applied (Amount −1,360.00 versus Open balance −210.00 \= 1,150.00 applied). When the Amount and Open balance totals diverge, the difference is always the net of payments and credit applications recorded against the listed transactions. The Open balance total — here 400,840.00 — is the figure that should reconcile to the Accounts Payable balance on your Balance Sheet for the same as-of date.

# **12  Common use cases**

The report earns its keep in everyday finance work. A few of the most common ways teams use it:

1. **Plan payments and protect cash.** Scan the open balances and due dates to decide what to pay this week without overcommitting cash.

2. **Stop late fees before they start.** The oldest bands flag bills slipping past their terms so you can pay or renegotiate before penalties hit.

3. **Prioritize who gets paid first.** Focus on the 61–90 and 91+ bands, or on critical vendors, to triage limited cash.

4. **Put vendor credits to work.** Spot unapplied credits — like the 210.00 still open on the Unimart credit — and apply them instead of paying cash.

5. **Close the month and reconcile.** Tie the total open balance back to the A/P balance on the Balance Sheet to confirm your books are clean.

6. **Investigate and resolve disputes.** Drill from a balance into the exact bill or credit behind it to answer a vendor’s question with confidence.

# **13  Best practices**

* Run the report on a regular cadence (weekly is common) so overdue items never pile up unnoticed.

* Reconcile the total open balance to the Accounts Payable balance on your Balance Sheet at month-end; investigate any difference.

* Watch the 91+ band closely — long-overdue bills signal cash-flow strain or, sometimes, a data-entry error.

* Clear out stale or fully-used vendor credits so the report reflects only credits you can still apply.

* Confirm each vendor’s payment terms are set correctly; the due date — and therefore the entire aging — depends on them.

* Save a customized version (filtered to a vendor or location, or with extra columns) so your go-to view is one click away.

# **14  FAQ and troubleshooting**

**Q.  Why is a bill I know about missing from the report?**

**A.**  Most likely it has been paid in full, so its open balance is zero and it drops off. Check that the bill falls inside the selected report period as well.

**Q.  Why are some amounts negative?**

**A.**  Negative lines are vendor credits. They reduce what you owe, so they carry a negative Amount and Open balance.

**Q.  Why does a credit appear in the 91+ band with no due date?**

**A.**  Credits usually have no due date, so they are aged by their transaction date. A credit dated months ago lands in an older band even though Due date and Past due are blank.

**Q.  Why don’t the Amount and Open balance totals match?**

**A.**  Because some transactions have been partially paid or partially applied. The difference equals the net of those payments and credit applications.

**Q.  What’s the difference between this and the A/P Aging Summary?**

**A.**  The Summary shows one netted row per vendor across aging columns; the Detail (this report) lists every individual transaction behind those balances.

**Q.  How do I change the aging buckets?**

**A.**  Open Customize → Aging and adjust the days per period and the number of periods. The bucket headings update automatically.

**Q.  Why is an item in “Current” when its date is in the past?**

**A.**  Current is based on the due date, not the transaction date. An item dated last month but due next week is not yet overdue, so it sits in Current.

**Q.  The total doesn’t match my Balance Sheet — what now?**

**A.**  Confirm both use the same as-of date and accounting method (Accrual vs Cash), then look for entries posted directly to A/P or items dated outside the report period.

# **15  Quick reference (cheat sheet)**

| Formulas Past due (days) — as-of date − Due date  (≤ 0 ⇒ Current) Open balance — Amount − payments/credits already applied Band subtotal — sum of Amount and of Open balance for lines in the band (bills − credits) Grand total — sum of all band subtotals |
| :---- |

| Reading the bands Current — due today or later (0 days past due) 1 – 30 / 31 – 60 / 61 – 90 — increasing degrees of lateness, 30 days apart 91 or more — the most overdue — watch this band closely Empty bands — are hidden; only bands with transactions appear |
| :---- |

Pilucent · Accounts Payable Reporting · A/P Aging Detail Report