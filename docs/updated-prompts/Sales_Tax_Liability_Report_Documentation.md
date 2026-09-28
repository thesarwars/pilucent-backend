

| BALANZIFY   ·   PRODUCT DOCUMENTATION Sales Tax Liability Report Logic · Calculations · Filtering · Columns · Data Representation · Use Cases |
| :---- |

This guide explains exactly how Balanzify builds the Sales Tax Liability Report. It walks through every column, the formulas behind each figure, how sales are grouped by tax agency and split into the rate components that make up each jurisdiction’s tax, the controls that shape the report, and the day-to-day decisions it is designed to support. It is written for U.S. small-business owners, bookkeepers, and accountants who need to know — quickly and accurately — how much sales tax they owe each agency and how that figure was reached.

**Module:**  Sales Tax · Reporting        **Market:**  U.S. SMB        **Version:**  1.0

Audience: Finance, Accounting & Bookkeeping teams

Last updated: June 2026

**Contents**

**1  Introduction**3

1.1  About this guide3

1.2  What the Sales Tax Liability Report is3

1.3  Why it matters3

**2  Key concepts and terminology**4

**3  How to read the report**4

3.1  The regions of the report4

3.2  Agencies and their rate components5

**4  Column reference**5

**5  How the numbers are built**6

5.1  The taxable base6

5.2  The tax for each rate6

5.3  Grouping by agency (and why only Tax totals)6

5.4  Cash vs accrual basis7

**6  Calculations**7

**7  Report controls and date range**7

**8  Filtering and customization**8

8.1  The controls and Customize panel8

8.2  Columns you can add8

**9  Data representation and formatting**8

**10  Transactions that feed the report**9

**11  Worked example: the sample report**9

11.1  The data9

11.2  How the key numbers are derived10

11.3  Reconciling to Sales Tax Payable10

**12  Common use cases**11

**13  Best practices**11

**14  FAQ and troubleshooting**11

**15  Quick reference (cheat sheet)**12

# **1  Introduction**

## **1.1  About this guide**

Balanzify reports are most useful when you know precisely what each number means and where it comes from. This document removes the guesswork from the Sales Tax Liability Report. By the end of it you should be able to read any line on the report with confidence, reproduce every total by hand, and use it to file accurate returns — answering the questions that matter at filing time: “how much do I owe each agency?”, “what part of my sales was taxable?”, and “does this tie out to my books?”

## **1.2  What the Sales Tax Liability Report is**

The Sales Tax Liability Report summarizes the sales tax your business has **collected and owes** over a date range, organized by the **tax agency** you remit it to. Within each agency, it breaks the tax down into the individual rate components that make up the jurisdiction — state, county, city, and special districts — and for each one it shows the sales it applied to, how much of those sales was taxable, and the tax due. It is the single report you reach for when it is time to prepare a sales tax return.

It is built for the way sales tax actually works in the United States: a single sale can be subject to several layers of tax at once (for example, a California sale carries state, county, city-district, and county-district rates together), and you may owe more than one agency if you sell into more than one state. The report keeps each agency’s liability clearly separated so you can file each return on its own.

It pairs with the Sales Tax Liability Summary, which collapses each agency to a single payable figure; this Detail view shows the component rates and the taxable and non-taxable sales behind that figure.

## **1.3  Why it matters**

* It tells you exactly how much sales tax to remit to each agency for the period — the number you put on the return.

* It separates taxable from non-taxable (exempt) sales, which is what most returns ask you to report.

* It breaks tax down by jurisdiction component (state / county / city / district), the level many U.S. returns require.

* It supports audits: every figure traces back to the sales recorded in the period.

* It reconciles your books: each agency total should match the Sales Tax Payable owed to that agency in your ledger.

| At a glance Purpose — Summarize sales tax collected and owed, ready for filing. Source — Taxable and non-taxable sales recorded in the date range. Grouping — By tax agency, then by each rate component within the agency. Shows — Gross total, non-taxable, taxable amount, and tax amount per rate. Agency total — Sums the Tax Amount only — the amount payable to that agency. Basis — Accrual (tax recognized at invoice) or Cash (at payment) — your choice. Key figure — Tax Amount \= what you owe; the agency total is what you remit. |
| :---- |

# **2  Key concepts and terminology**

A handful of terms appear throughout the report and this guide. Skim these once and the rest of the document reads easily.

| Term | What it means |
| :---- | :---- |
| **Tax agency** | The government body you collect for and remit to — e.g. the New York Department of Taxation and Finance or the California Department of Tax and Fee Administration. |
| **Tax rate / component** | A single percentage that makes up part of a jurisdiction’s tax — a state, county, city, or special-district rate. Several can apply to one sale. |
| **Jurisdiction** | The place whose rules tax a sale, usually where the customer takes delivery. It determines which agency and which component rates apply. |
| **Gross total** | All sales associated with a rate in the period — taxable and non-taxable combined. |
| **Non-taxable** | The part of gross sales that is exempt — exempt customers, exempt products, or sales outside the taxing jurisdiction. |
| **Taxable amount** | The base the tax is actually charged on: Gross total − Non-taxable. |
| **Tax amount** | The tax itself for that rate: Taxable amount × the rate. |
| **Accounting method** | Whether tax is recognized when you invoice (Accrual) or when the customer pays (Cash). |
| **Sales Tax Payable** | The liability account in your books that holds collected tax until you remit it. |
| **Nexus** | The connection (physical or economic) that obliges you to collect and remit tax in a given state — why an SMB may owe more than one agency. |

# **3  How to read the report**

## **3.1  The regions of the report**

From top to bottom, the report is organized into a few predictable regions. Knowing what each one does makes the whole report easy to scan.

| Region | Where it is | What it does |
| :---- | :---- | :---- |
| **Report title** | Top, centered | Names the report and shows the company and the date range it covers. |
| **Controls** | Top bar | Tax Agency filter, the Cash/Accrual toggle, and the Run report button (see Section 7). |
| **Toolbar** | Top-right icons | Add notes, email, print, export, and report settings. |
| **Column headers** | Below the title | Label the five columns: Tax name and the four money columns. |
| **Agency group header** | Shaded row | Starts an agency’s section, e.g. “New York Department of Taxation and Finance.” |
| **Rate rows** | Under each agency | One row per rate component (state, county, city, district) or named tax rate. |
| **Agency total** | “Total for …” row | Sums the Tax Amount for that agency — the amount you remit to it. |
| **Footer** | Bottom, centered | States the accounting basis and the date and time the report was run. |

## **3.2  Agencies and their rate components**

The report groups everything by the tax agency you pay. Under each agency sits one row for every rate that contributed tax in the period. Some agencies levy a single combined rate; others, like California, layer several — a state rate plus county, city-district, and county-district rates — and each appears on its own line, all charged on the same sale. Reading an agency block top to bottom shows you every slice of tax that rolls up into that agency’s payable. Agencies with no activity in the period are simply omitted.

# **4  Column reference**

Below is every column on the report, what it shows, and where its value comes from.

| Column | What it shows | Where it comes from / how it is calculated |
| :---- | :---- | :---- |
| **Tax name** | The agency, and beneath it each rate component or named tax rate. | Agencies come from your tax setup; the indented rows are the rates that make them up (e.g. California State, California, San Mateo County). |
| **Gross total** | All sales tied to this rate in the period. | The sum of sales amounts on transactions where this rate applied — taxable and non-taxable together, before any exemption is removed. |
| **Non-taxable** | The exempt portion of those sales. | Sales that carried the rate’s jurisdiction but were not taxed — exempt customers, exempt items, or out-of-jurisdiction sales. |
| **Taxable amount** | The base the tax is charged on. | Gross total − Non-taxable. This is the figure the rate is applied to. |
| **Tax amount** | The tax due for this rate. | Taxable amount × the rate’s percentage. Small differences from an exact percentage come from rounding tax on each transaction. |

At the agency level, only the Tax Amount is totaled. The Gross, Non-taxable, and Taxable columns are left blank on the “Total for …” row on purpose — see Section 5.3 for why summing them would double-count.

# **5  How the numbers are built**

## **5.1  The taxable base**

Every rate row starts from the sales it touched. Balanzify gathers all sales in the period that carry the rate’s jurisdiction, splits them into the exempt part and the part that is actually taxed, and the difference is the base the rate is charged on:

| Gross total      \=  all sales carrying this rate (taxable \+ non-taxable) Taxable amount   \=  Gross total  −  Non-taxable   Non-taxable includes: exempt customers, exempt products, and sales outside the taxing jurisdiction. |
| :---- |

## **5.2  The tax for each rate**

Each rate’s tax is its taxable base times the rate’s percentage. The report rounds tax on each transaction, so an agency’s line can differ from the exact percentage of the period’s base by a cent or two:

| Tax amount  \=  Taxable amount  ×  rate %   e.g.  New York State:  2,100.00 × 4.000%  ≈  83.99       New York City:   2,100.00 × 4.875%  ≈  102.38       Sales Tax:       20,000.00 × 10.00% \=  2,000.00 |
| :---- |

## **5.3  Grouping by agency (and why only Tax totals)**

Rows are grouped under the agency you remit to, and each agency ends with a “Total for …” row. That total sums the Tax Amount column only — and that is deliberate. The same sale is often charged by several component rates of one agency (in the sample, the same $45,000 of California sales is taxed by the state, county, city-district, and county-district rates). Adding up the Gross or Taxable columns across those rows would count that $45,000 four times. The Tax Amount, by contrast, is a different, additive slice on each row, so summing it gives the true amount payable to the agency.

| Agency tax total  \=  sum of Tax Amount over the agency's rate rows   California:  2,812.50 \+ 450.00 \+ 112.50 \+ 956.25  \=  4,331.25 (Gross / Taxable are NOT summed — they would double-count the same sales.) |
| :---- |

## **5.4  Cash vs accrual basis**

The Cash/Accrual toggle decides when a sale’s tax counts. On an Accrual basis, tax is recognized when you issue the invoice; on a Cash basis, only when the customer actually pays. Many states let a small business report on either basis, but you must use the one your state requires — and the same report can swing materially between the two if you carry large unpaid invoices. The sample is run on the Accrual basis, as noted in its footer.

# **6  Calculations**

Every figure on the report can be reproduced with a few simple rules.

**6.1  Taxable amount.**  Taxable amount \= Gross total − Non-taxable. In the New York rows, gross sales of 2,600.00 less 500.00 of non-taxable sales leaves a taxable base of 2,100.00; the California rows have no exemptions, so the full 45,000.00 is taxable.

**6.2  Tax amount.**  Tax amount \= Taxable amount × the rate’s percentage. New York State’s 4% on 2,100.00 is about 83.99; New York City’s combined 4.875% on the same 2,100.00 is 102.38; the flat 10% “Sales Tax” on 20,000.00 is exactly 2,000.00. Small gaps from the round percentage are because tax is rounded on each individual sale, then added up.

**6.3  Agency total.**  The “Total for …” row adds the Tax Amount across the agency’s rate rows. New York: 83.99 \+ 102.38 \+ 2,000.00 \= 2,186.37. California: 2,812.50 \+ 450.00 \+ 112.50 \+ 956.25 \= 4,331.25. These are the amounts you remit to each agency.

**6.4  Total liability for the period.**  Your overall sales-tax liability is the sum of the agency totals — here 2,186.37 \+ 4,331.25 \= 6,517.62 across the two agencies. Because each agency is filed and paid separately, the report keeps them as distinct totals rather than blending them into one number.

# **7  Report controls and date range**

Three controls at the top of the report shape what it shows. Set them, then choose Run report.

* **Tax Agency —** limits the report to one agency, or shows them all. The sample is set to All, so both the New York and California agencies appear. Filter to a single agency when you are preparing that one return.

* **Accounting method —** the Cash / Accrual toggle (see Section 5.4). Accrual counts tax when you invoice; Cash counts it when you are paid. The sample uses Accrual.

* **Date range —** the filing period the report covers. The sample runs January 1 – June 24, 2026\. Set this to the exact period each agency’s return asks for.

The date range can be a custom From/To (as in the sample) or one of the ready-made periods below.

| Range | What it does |
| :---- | :---- |
| **Custom (From / To)** | Pick the exact start and end dates of the filing period — the most precise choice for matching a return. |
| **Today / This week / This month** | Quick current-period views; the “to date” variants stop at today. |
| **This quarter / This fiscal quarter** | The current calendar or fiscal quarter — common for quarterly filers. |
| **This year / This fiscal year** | The current calendar or fiscal year — for annual filers and year-end checks. |
| **Last month / quarter / year** | The matching prior period, for filing a return after the period has closed. |
| **All Dates** | Every taxable transaction on record — useful for a full reconciliation rather than a single filing. |

Whatever you pick, the date range only sets which sales are in scope; the agency grouping and the per-rate math work the same way underneath.

# **8  Filtering and customization**

## **8.1  The controls and Customize panel**

Beyond the three top-bar controls, the report settings (the gear) let you reshape the report. The most useful options:

* **Number format —** show or hide cents, divide by 1,000, hide zero rows, and show negatives in red or in parentheses (handy when returns and credits pull a figure below zero).

* **Rows / Columns —** choose which columns appear and in what order, and whether to keep the grouping by agency.

* **Filter —** narrow by tax agency (also on the top bar) when you keep several and want one return at a time.

* **Header / Footer —** control the company name, report title, the basis label, and the prepared date/time shown on the printout.

Once a report is set up the way a particular filing needs it, save it as a custom report so the same view is one click away each period.

## **8.2  Columns you can add**

Beyond the defaults, you can surface extra columns when a return or a review needs more context. Common additions include:

* Tax rate (the percentage applied), so the math on each line is explicit

* Taxable \+ Non-taxable split shown side by side with their own subtotals

* Adjustments (manual sales-tax adjustments recorded for the agency)

* Component breakdown by jurisdiction level (state / county / city / district)

* Prior balance and payments (to show the net amount still due)

# **9  Data representation and formatting**

How the report displays its data is just as important as the numbers themselves:

* **Grouping —** rows are grouped by tax agency; each agency carries a header and a “Total for …” row that totals the Tax Amount.

* **The four money columns —** Gross total, Non-taxable, Taxable amount, and Tax amount are right-aligned and formatted as currency; agency totals show only in the Tax Amount column.

* **Indentation —** rate components are indented beneath their agency, so the state / county / city / district structure reads at a glance.

* **Emphasis —** agency totals are bold and set off with a rule line; the headline figure for each agency is its Tax Amount total.

* **Basis and timestamp —** the footer states whether the report is on a Cash or Accrual basis and the date and time it was run — important to record alongside a filed return.

* **Share and export —** the toolbar lets you add notes, email, print, or export the report to a spreadsheet or PDF, preserving the grouping and totals.

# **10  Transactions that feed the report**

The report is built from the sales you record in the period. The ones that shape it:

* **Invoices —** taxable sales billed to customers. They add to Gross total, and to Taxable amount and Tax amount when tax applies. On an Accrual basis they count when issued; on a Cash basis, when paid.

* **Sales receipts —** sales paid at the point of sale. They feed the report the same way as invoices and count under either basis when the sale is recorded.

* **Credit memos and refunds —** customer returns and credits. They reduce Gross, Taxable, and Tax — lowering what you owe the agency for the period.

* **Non-taxable / exempt sales —** sales to exempt customers, of exempt products, or outside the jurisdiction. They add to Gross total and to Non-taxable, but not to Taxable amount or Tax amount.

* **Sales-tax adjustments —** manual adjustments (for discounts, credits, or corrections an agency allows) change the tax owed without a new sale.

Purchases, bills, payroll, and other non-sales transactions do not appear — this report is about tax on what you sell. If a sale is missing, check that it falls inside the date range and that the right tax rate and customer/product tax status were applied.

# **11  Worked example: the sample report**

## **11.1  The data**

Below is a faithful recreation of the sample Sales Tax Liability Report for Halo Axis, on an Accrual basis for January 1 – June 24, 2026\. It covers two agencies — the New York Department of Taxation and Finance and the California Department of Tax and Fee Administration — each with its rate components and an agency total.

| TAX NAME | GROSS TOTAL | NON-TAXABLE | TAXABLE AMOUNT | TAX AMOUNT |
| :---- | ----: | ----: | ----: | ----: |
| **New York Department of Taxation and Finance** |  |  |  |  |
| New York State | 2,600.00 | 500.00 | 2,100.00 | 83.99 |
| New York, New York City | 2,600.00 | 500.00 | 2,100.00 | 102.38 |
| Sales Tax | 20,000.00 | 0.00 | 20,000.00 | 2,000.00 |
| **Total for New York Department of Taxation and Finance** |  |  |  | **$2,186.37** |
| **California Department of Tax and Fee Administration** |  |  |  |  |
| California State | 45,000.00 | 0.00 | 45,000.00 | 2,812.50 |
| California, San Mateo County | 45,000.00 | 0.00 | 45,000.00 | 450.00 |
| California, San Mateo City District | 45,000.00 | 0.00 | 45,000.00 | 112.50 |
| California, San Mateo County District | 45,000.00 | 0.00 | 45,000.00 | 956.25 |
| **Total for California Department of Tax and Fee Administration** |  |  |  | **$4,331.25** |

## **11.2  How the key numbers are derived**

**The taxable base.** In New York, gross sales of 2,600.00 include 500.00 of non-taxable sales, so the taxable base is 2,100.00. The “Sales Tax” line has no exemptions, so its full 20,000.00 is taxable. Every California line is fully taxable at 45,000.00.

**Tax per rate.** Each line is its taxable base times the rate. New York State at 4% on 2,100.00 ≈ 83.99; New York City’s combined 4.875% on 2,100.00 \= 102.38; the flat 10% Sales Tax on 20,000.00 \= 2,000.00.

**Same sale, several rates (California).** The same 45,000.00 of California sales is taxed by four component rates at once — state 6.25% (2,812.50), San Mateo County 1% (450.00), San Mateo City District 0.25% (112.50), and San Mateo County District 2.125% (956.25). Together they are San Mateo’s combined 9.625% rate; 45,000.00 × 9.625% \= 4,331.25.

**Agency totals.** Each “Total for …” row adds only the Tax Amount: New York 83.99 \+ 102.38 \+ 2,000.00 \= 2,186.37, and California 2,812.50 \+ 450.00 \+ 112.50 \+ 956.25 \= 4,331.25.

| Why the agency total sums only the Tax column Notice all four California rows show the same 45,000.00 gross and taxable. That is one set of sales taxed by four overlapping rates — not 180,000.00 of sales. Adding the Gross or Taxable columns would count those sales four times. The Tax Amount is different on each row, and each is a separate slice you actually owe, so summing just that column gives the real payable — 4,331.25. That is why the Gross, Non-taxable, and Taxable columns stay blank on the total line. |
| :---- |

## **11.3  Reconciling to Sales Tax Payable**

Each agency total should match the Sales Tax Payable your books owe that agency for the same period and basis — 2,186.37 to New York and 4,331.25 to California, a combined 6,517.62 in liability. If a total doesn’t reconcile, the usual culprits are a sale with the wrong tax rate or customer/product tax status, a transaction dated just outside the range, a mismatch between the report’s basis (Cash vs Accrual) and how the liability was booked, or a manual journal entry posted straight to Sales Tax Payable. Matching the report’s basis and date range to your filing, then drilling into the agency that is off, is the fastest way to find the gap.

# **12  Common use cases**

The report earns its keep at every filing cycle. A few of the most common ways teams use it:

1. **Prepare and file sales tax returns.** Read each agency’s total to get the amount to report and remit for the period.

2. **File jurisdiction breakdowns.** Use the state / county / city / district rows for returns (like California’s) that require tax reported by component.

3. **Separate taxable from exempt sales.** Show the taxable and non-taxable split that most returns ask you to report — and keep proof for exemptions.

4. **Reconcile collected tax to the books.** Tie each agency total back to the Sales Tax Payable owed to that agency.

5. **Manage multi-state obligations.** Where you have nexus in more than one state, see each agency’s liability cleanly separated for its own filing.

6. **Support an audit.** Trace any figure back to the sales in the period, on the basis and date range the auditor specifies.

# **13  Best practices**

* Run the report for the exact filing period and on the basis (Cash or Accrual) your state requires; mismatches are the most common cause of a wrong figure.

* Reconcile each agency total to the Sales Tax Payable owed to that agency before you file.

* Keep tax rates and jurisdiction assignments current — rates change, and the report is only as right as your setup.

* Set customer and product tax statuses accurately (resale, exempt, non-taxable) so the Non-taxable column is trustworthy and audit-ready.

* File and pay each agency by its own due date; the report gives the amount, not the deadline.

* Save the report (and a PDF or export) with each return as part of your records, noting the basis and run time shown in the footer.

* Where you sell into multiple states, review nexus periodically so every agency you owe is set up and appears here.

# **14  FAQ and troubleshooting**

**Q.  Why do several rows show the same Gross and Taxable amount?**

**A.**  Because one sale can be taxed by several component rates of the same agency (state, county, city, district). Each rate gets its own row on the shared base, and only the Tax Amount differs.

**Q.  Why is there no Gross or Taxable total per agency?**

**A.**  Summing those columns across overlapping component rates would count the same sales multiple times. Only the Tax Amount — what you actually owe — is totaled.

**Q.  What’s the difference between Gross, Non-taxable, and Taxable?**

**A.**  Gross is all sales for the rate; Non-taxable is the exempt portion; Taxable is the base actually charged tax (Gross − Non-taxable).

**Q.  Should I run this on Cash or Accrual?**

**A.**  Match whatever your state requires. Accrual recognizes tax when you invoice; Cash recognizes it when the customer pays.

**Q.  Why is the Tax Amount a cent off from rate × taxable (83.99 vs 84.00)?**

**A.**  Tax is rounded on each individual sale and then added up, so the period total can differ slightly from applying the percentage to the combined base.

**Q.  What’s the difference between this and the Sales Tax Liability Summary?**

**A.**  The Summary shows one payable figure per agency; this Detail shows the component rates and the taxable and non-taxable sales behind it.

**Q.  How does this tie to my books?**

**A.**  Each agency total should reconcile to the Sales Tax Payable owed to that agency for the same period and basis.

**Q.  A sale I expected is missing — why?**

**A.**  Check that it falls inside the date range and that the sale carried the correct tax rate and the customer/product tax status you intended.

# **15  Quick reference (cheat sheet)**

| Formulas Taxable amount — Gross total − Non-taxable Tax amount (per rate) — Taxable amount × rate % Agency total — sum of Tax Amount over the agency’s rate rows (Gross/Taxable are not summed) Period liability — sum of the agency totals (filed separately per agency) Reconciles to — Sales Tax Payable owed to each agency |
| :---- |

| Reading the report Grouping — by tax agency, then by rate component (state / county / city / district) Same base, many rates — one sale can appear under several component rates of one agency Agency total — Tax Amount only — the amount you remit to that agency Basis — Accrual \= tax at invoice; Cash \= tax at payment (shown in the footer) |
| :---- |

Balanzify · Sales Tax Reporting · Sales Tax Liability Report