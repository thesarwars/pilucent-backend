  
**PILUCENT**

Accounting & Bookkeeping Platform

**Taxable Sales Summary**

**Report**

Product & Reporting Documentation

Functional Specification · US Small & Mid-Sized Business

*Logic · Calculations · Filtering · Columns · Data Representation · Use Cases*

| Document | Taxable Sales Summary — Functional Specification |
| :---- | :---- |
| **Module** | Reports → Sales Tax → Taxable Sales Summary |
| **Market** | United States — small & mid-sized businesses |
| **Audience** | Owners, bookkeepers, accountants, and product / engineering teams |
| **Version** | 1.0 |
| **Status** | Draft for implementation |

**Table of Contents**

[**1\. Introduction & Overview	3**](#heading=)

[1.1 What the report answers	3](#heading=)

[1.2 Who uses it	3](#heading=)

[1.3 Where it sits in the sales tax workflow	4](#heading=)

[**2\. Key Concepts & Terminology	5**](#heading=)

[**3\. Anatomy of the Report	6**](#heading=)

[3.1 The control strip	6](#heading=)

[3.2 The report header	6](#heading=)

[3.3 The data grid	6](#heading=)

[3.4 The footer	6](#heading=)

[**4\. Columns Explained	7**](#heading=)

[**5\. The Taxability Logic (Core Engine)	8**](#heading=)

[5.1 Test one — is the line taxable?	8](#heading=)

[5.2 Test two — is it inside the period and basis?	8](#heading=)

[5.3 Test three — which row does it belong to?	8](#heading=)

[5.4 What amount is added	8](#heading=)

[**6\. Calculation Methodology	9**](#heading=)

[6.1 Pass 1 — per line	9](#heading=)

[6.2 Pass 2 — per item (each row)	9](#heading=)

[6.3 Pass 3 — per category and the grand total	9](#heading=)

[**7\. What Data Appears on the Report	10**](#heading=)

[7.1 Source transactions	10](#heading=)

[7.2 What is excluded	10](#heading=)

[7.3 Edge cases to expect	10](#heading=)

[7.4 Accounting basis matters	10](#heading=)

[**8\. Filtering & Customization	11**](#heading=)

[**9\. Data Representation & Formatting	12**](#heading=)

[**10\. Worked Example — Reading a Real Report	13**](#heading=)

[10.1 The report as displayed	13](#heading=)

[10.2 Reading each row	13](#heading=)

[10.3 Verifying the total	13](#heading=)

[**11\. Reconciliation & Validation	15**](#heading=)

[11.1 The key relationships	15](#heading=)

[11.2 Common reasons figures might differ	15](#heading=)

[**12\. Use Cases & Business Scenarios	16**](#heading=)

[**13\. Best Practices	17**](#heading=)

[**14\. FAQ & Troubleshooting	18**](#heading=)

[**15\. Glossary	19**](#heading=)

# **1\. Introduction & Overview**

The Taxable Sales Summary Report in Pilucent shows how much of a business’s sales were subject to sales tax, broken down by product or service, for a chosen period and accounting basis. For a US small or mid-sized business, it is the report that answers the central question on every sales tax return: “of everything we sold, how much was taxable?” It isolates the taxable sales base — the amount that sales tax is calculated on — from exempt and non-taxable sales, and rolls it up into a single, filing-ready figure.

Each row is a product or service, and the Total column is the taxable sales amount for that item over the period. Items can be grouped under categories with their own subtotals, and a grand total at the bottom gives the company-wide taxable sales. Because sales tax in the United States is administered state by state (and often by county and city), this total is what a business carries to the taxable-sales line of the return it files with each tax agency it is registered in.

| Implementation note — what this report is, in one sentence For each taxable line on a sales transaction (invoice, sales receipt, credit memo, or refund receipt) dated within the report period under the selected basis, take the line’s sales amount, group it by the product or service on the line, and sum. Categories roll into subtotals; lines with no product or service fall into an unlabeled bucket; credits, returns, and discounts net in as negatives. The grand total is the taxable sales base for the period. |
| :---- |

## **1.1 What the report answers**

A single Taxable Sales Summary is designed to answer three questions at a glance:

* **How much of our sales was taxable?** The grand total is the taxable sales base for the period and basis.

* **Which products or services drove it?** Each item has its own row, and categories roll up into subtotals.

* **Does it reconcile to what we owe?** The taxable base ties to the sales tax liability and the figure reported on the return.

## **1.2 Who uses it**

| Role | Why they rely on it |
| :---- | :---- |
| **Business owner / founder** | Sees the taxable revenue that drives the sales tax bill and which products contribute most. |
| **Bookkeeper** | Pulls the taxable sales base when preparing each sales tax filing and checks it before submitting. |
| **Accountant / Controller** | Reconciles taxable sales to the sales tax liability and supports the numbers at filing time. |
| **Tax preparer** | Uses the per-jurisdiction taxable base to complete state and local sales tax returns. |
| **Auditor / Reviewer** | Separates taxable from exempt sales and traces totals to source transactions during a sales tax audit. |
| **Product / Engineering** | Treats this document as the functional specification for building the report into the platform. |

## **1.3 Where it sits in the sales tax workflow**

Every time you create an invoice, sales receipt, credit memo, or refund, Pilucent records whether each line is taxable and how much sales tax applies. The Taxable Sales Summary is the reporting lens over that activity: it reads the taxable sales lines and re-presents them by product or service. It does not create or change any data, so the report is always only as accurate as the tax settings on your items and customers and the transactions behind them.

| Taxable vs. total vs. tax collected Three figures are easy to confuse. Total sales is everything you sold. Taxable sales (this report) is the portion subject to sales tax — total sales minus exempt and non-taxable sales. Sales tax collected is the tax itself, calculated on the taxable base; that lives on the Sales Tax Liability report, not here. This report shows the base, not the tax. |
| :---- |

# **2\. Key Concepts & Terminology**

A few core ideas drive everything in this report. Getting comfortable with them makes the calculations and settings that follow easy to read.

| Term | Meaning in Pilucent |
| :---- | :---- |
| **Taxable sales** | The portion of sales that is subject to sales tax. This report sums the taxable sales amount, grouped by product or service. |
| **Non-taxable / exempt sales** | Sales not subject to sales tax — for example, sales to an exempt customer, resale, or a product that is not taxable. These are excluded here. |
| **Sales tax** | A tax charged on taxable sales, set by the state and often county and city. It is calculated on the taxable base but is not shown on this report. |
| **Product / Service (item)** | The line item sold on a sales form. The report groups taxable amounts by the product or service on each line. |
| **Category** | An optional grouping of products or services (for example, “Gadget”). Categories produce subtotals on the report. |
| **Accrual basis** | Sales are counted when invoiced, regardless of when paid. |
| **Cash basis** | Sales are counted when payment is received, not when invoiced. |
| **Tax status** | The flag on an item or customer that marks a line as taxable or exempt; it decides what this report includes. |
| **Jurisdiction** | A taxing authority — a state, county, or city — to which a business reports and remits sales tax. |

# **3\. Anatomy of the Report**

The screen is made up of a control strip, a report header, the data grid, and a footer. Knowing each region makes the rest of this document easier to follow.

## **3.1 The control strip**

Running across the top of the report are the controls used to shape and share it:

* **Report period —** the date range of transactions included (for example, “All Dates,” or a specific month or quarter to match a filing).

* **Accounting method —** a Cash / Accrual toggle. It should match the basis you file sales tax on; the example uses Accrual.

* **Display columns by —** splits the single Total into columns — for example by month, quarter, customer, class, or location.

* **Compare to —** adds a second period side by side (for example, the prior quarter or year) for trend analysis.

* **Customize and Save As —** open the full settings panel and store a reusable saved version aligned to your filing.

* **Refresh, Print, Export, Compact, zoom —** regenerate, print or export, and tighten or scale the on-screen view (Compact | 100%). Display only — never the numbers.

## **3.2 The report header**

Centered above the grid, the header identifies exactly what you are looking at:

* **Company name** — the business the report belongs to (for example, Halo Axis).

* **Report title** — “Taxable Sales Summary.”

* **Date basis** — the selected report period (for example, “All Dates”).

## **3.3 The data grid**

The body lists each product or service as a row, with its taxable sales in the Total column. Items can be grouped under a collapsible category that shows a “Total for \[Category\]” subtotal, and a single unlabeled row at the top collects taxable amounts that were not tied to any product or service. The bottom Total row sums everything. A sort control on the Total header ranks rows by amount.

## **3.4 The footer**

Below the grid, Pilucent shows the accounting basis and stamps the exact date, time, and time zone the report was generated (for example, “Accrual basis | Wednesday, June 24, 2026 03:32 PM GMT+06:00”). Because the basis and the run moment both affect the figures, this line is part of the audit trail. There is also an option to attach a note.

# **4\. Columns Explained**

In its default form the report has just two visible columns: the row label (the product or service) and a single Total. The control strip can expand that single Total into many columns.

| Column | What it represents | How it is derived |
| :---- | :---- | :---: |
| **Product / Service** | The item the row describes. Categories appear as group headers; an unlabeled row holds amounts with no item. | Line’s product / service |
| **Total** | The taxable sales amount for that row over the period and basis. | Sum of taxable lines |
| **Total for \[Category\]** | A subtotal of all items within a category (for example, “Total for Gadget”). | Sum of the category’s items |
| **Grand TOTAL (row)** | The company-wide taxable sales for the period — the filing-ready base. | Sum of all rows |

| Expanding the single Total column “Display columns by” turns the one Total into a grid — for instance a column per month so you can see taxable sales across a quarter at a glance, or a column per customer or location. “Compare to” adds a prior period beside the current one. The row logic never changes; only how the taxable amount is sliced into columns does. |
| :---- |

# **5\. The Taxability Logic (Core Engine)**

Strip everything else away and the report answers one question per sales line: was this line taxable, and if so, how much of the sale does it add to the taxable base? Three tests decide whether a line is counted and where it lands.

## **5.1 Test one — is the line taxable?**

A line is included only if it is taxable. Taxability comes from the combination of the item’s tax status and the customer’s tax status: a taxable product sold to a regular customer is taxable; the same product sold to an exempt customer (for example, one with a valid resale or exemption certificate) is not. Non-taxable items and exempt sales are left out and instead appear on the non-taxable side of sales reporting.

## **5.2 Test two — is it inside the period and basis?**

The line must fall within the report period under the selected accounting method. On an accrual basis the line is dated by its invoice or sales-receipt date; on a cash basis it is recognized when the customer pays, so the timing — and sometimes the amount — can differ between the two bases for the same sale.

| Counted  if  Taxable \= true  AND  Date ∈ Period (on selected basis) |
| :---: |

## **5.3 Test three — which row does it belong to?**

Each counted line is placed by the product or service on the line:

| Line situation | Where it lands |
| :---- | :---- |
| **Item belongs to a category** | Under that category, contributing to its “Total for \[Category\]” subtotal. |
| **Item has no category** | On its own row, listed directly. |
| **No product / service on the line** | In the unlabeled bucket at the top of the report. |
| **Item later deleted** | Still shown, on its historical row, marked “(deleted).” |

## **5.4 What amount is added**

The amount counted is the taxable sales amount of the line — the price charged for the goods or service after any line discount — and it excludes the sales tax itself. Credits, returns, and refunds enter as negative amounts, reducing the taxable base, which is why a row (or the no-item bucket) can show a negative figure.

| The sales tax is never in the number If a customer is charged $100 for a taxable item plus $8 sales tax, this report counts $100, not $108. The report is the base that tax is calculated on, so adding the tax back in would double-count. The $8 belongs on the Sales Tax Liability report. |
| :---- |

# **6\. Calculation Methodology**

The report is built in three passes: per line, per item, and per category, finishing with the grand total. Every pass is a simple sum, which is what makes the figure quick to verify and to reconcile.

## **6.1 Pass 1 — per line**

1. Walk every sales transaction line in the period on the selected basis (invoices, sales receipts, credit memos, refund receipts).

2. Keep only lines that are taxable; drop exempt and non-taxable lines.

3. Take each kept line’s sales amount after discounts, excluding sales tax. Credits and refunds carry a negative sign.

## **6.2 Pass 2 — per item (each row)**

All taxable line amounts for the same product or service are summed onto one row:

| Item Total  \=  Σ (taxable line amounts for that item) |
| :---: |

## **6.3 Pass 3 — per category and the grand total**

Items in a category roll up into a subtotal; every row then sums to the company-wide total, including the unlabeled no-item bucket:

| Category Total  \=  Σ (item totals in the category) |
| :---: |
| **Grand Total  \=  Σ (all item & category totals)  \+  No-item bucket** |

| A useful cross-check Taxable sales and non-taxable sales should add up to total sales for the same period and basis (the figure on a Sales by Product/Service summary). If taxable plus non-taxable does not equal total sales, an item’s tax status or a transaction is likely miscoded — a fast way to catch configuration errors before filing.  |
| ----- |
| **Taxable Sales  \+  Non-Taxable Sales  \=  Total Sales** |

# **7\. What Data Appears on the Report**

The report reads the taxable lines of sales transactions, and nothing else. Understanding what is in and out makes the numbers predictable — and is the inclusion rule to build against.

## **7.1 Source transactions**

| Transaction type | Effect on taxable sales | Sign |
| :---- | :---: | :---: |
| **Invoice (taxable lines)** | Increases | Positive (+) |
| **Sales receipt (taxable lines)** | Increases | Positive (+) |
| **Credit memo (taxable lines)** | Decreases | Negative (–) |
| **Refund receipt (taxable lines)** | Decreases | Negative (–) |
| **Discount on a taxable line** | Decreases | Reduces the line |

## **7.2 What is excluded**

* Non-taxable and exempt sales — they belong to the non-taxable side of sales reporting.

* The sales tax amount itself — the report shows the base, not the tax collected.

* Purchases, expenses, and anything that is not a sale.

* Income recorded by journal entry with no product or service — it has no item to group by and generally will not appear as taxable sales.

## **7.3 Edge cases to expect**

Three patterns are normal on this report and should be handled, not treated as errors:

* **Deleted items still appear.** If an item had taxable sales in the period, its history is preserved and the row is marked “(deleted).” The amount still counts toward the total.

* **An unlabeled row.** Taxable amounts on lines with no product or service assigned collect in a single row with a blank label at the top. Assigning items keeps this clean.

* **Negative figures.** Credit memos, refunds, and discounts on taxable sales reduce the base and can make a row negative, including the no-item bucket.

## **7.4 Accounting basis matters**

Because sales tax can be filed on either basis depending on the state and the business, the Cash / Accrual toggle directly changes what this report shows. Always run it on the same basis you file, or the taxable base will not match the return.

# **8\. Filtering & Customization**

Everything about the report’s shape can be adjusted from the control strip and the Customize panel. The most important settings are below; any combination can be saved as a named report aligned to a filing.

| Setting | What it controls | Default / example |
| :---- | :---- | :---: |
| **Report period** | The date range included. Match it to your filing period (month, quarter, or year). | All Dates |
| **Accounting method** | Cash or accrual recognition; match your filing basis. | Accrual |
| **Display columns by** | Splits the Total into columns — by period, customer, class, or location. | Total only |
| **Compare to** | Adds a second period beside the current one for trends. | None |
| **Product / service filter** | Limit to one item, a category, or all. | All |
| **Customer / location filter** | Limit to a customer, class, or location — useful for per-jurisdiction views. | All |
| **Rows shown** | Hide zero rows, or show all items including inactive. | Non-zero |
| **Layout & zoom** | Compact or full layout and on-screen scale. | Compact | 100% |

| Filing-aligned views (US) A practical pattern for US filers is to save one version per return: the right period, the basis you file on, and a location or customer filter that matches the jurisdiction you are reporting to. With those saved, each filing period becomes a one-click refresh rather than a re-setup, and the saved basis prevents accidental cash/accrual mismatches. |
| :---- |

# **9\. Data Representation & Formatting**

How the figures are displayed follows consistent conventions so the report reads cleanly at a glance.

| Convention | How it appears |
| :---- | :---- |
| **Amounts** | Shown with thousands separators and two decimals (for example, 65,500.00); the grand total carries the currency symbol ($91,580.00). |
| **Subtotals** | Category subtotals are bold and labeled “Total for \[Category\]” (for example, $100.00 for Gadget). |
| **Grand total** | The bottom Total row is bold and clearly separated from the item rows. |
| **Categories** | Shown as collapsible group headers; items inside are indented beneath them. |
| **Deleted items** | Kept on their historical row and labeled “(deleted)” so the figure is still traceable. |
| **No-item bucket** | A single row with a blank label, holding taxable amounts not tied to a product or service. |
| **Negative values** | Shown with a leading minus sign (for example, \-20.00) and may appear in red. |
| **Sorting** | The Total header includes a sort control to rank rows by amount, highest or lowest first. |
| **Basis & timestamp** | The footer states the basis (for example, “Accrual basis”) and the exact run date, time, and time zone. |
| **Compact, zoom & export** | Compact and zoom are display-only; the report can also be refreshed, printed, or exported. |

# **10\. Worked Example — Reading a Real Report**

The example below is a Taxable Sales Summary for a company called Halo Axis, run for All Dates on an accrual basis as of June 24, 2026\. We will reproduce it exactly, then walk through every number so the logic in Sections 5 and 6 becomes concrete.

## **10.1 The report as displayed**

|  | Total |
| :---- | ----: |
|  | \-20.00 |
| Air Pod 3nd Gen | 65,500.00 |
| **▾ Gadget** |  |
| Air Pod 2nd Gen (deleted) | 100.00 |
| **Total for Gadget** | **$100.00** |
| Galaxy S25 Ultra 256GB | 26,000.00 |
| **TOTAL** | **$91,580.00** |

## **10.2 Reading each row**

**The unlabeled top row (-20.00).** This is the no-item bucket. A taxable amount of \-20.00 was recorded on a sales line with no product or service assigned — typically a discount or a small credit entered without an item. It reduces the taxable base by 20.00. Assigning it to a product would move it onto a named row and tidy the report.

**Air Pod 3nd Gen (65,500.00).** An uncategorized item shown on its own row. At 65,500.00 it is by far the largest source of taxable sales and drives most of the company-wide total.

**Gadget category (subtotal $100.00).** A category containing a single item, “Air Pod 2nd Gen (deleted).” Even though that product has been deleted, its 100.00 of historical taxable sales still appears, grouped under Gadget, and the “Total for Gadget” subtotal is therefore $100.00. Deleted items are retained so prior periods stay complete and auditable.

**Galaxy S25 Ultra 256GB (26,000.00).** Another uncategorized item, and the second-largest contributor to taxable sales at 26,000.00.

## **10.3 Verifying the total**

The grand total can be reproduced exactly using the three-pass method:

| Figure | How it is reached |
| :---- | :---- |
| **No-item bucket** | A single line with no product / service: \-20.00. |
| **Air Pod 3nd Gen** | Uncategorized item row: 65,500.00. |
| **Total for Gadget** | Category subtotal of its one item (Air Pod 2nd Gen, deleted): $100.00. |
| **Galaxy S25 Ultra 256GB** | Uncategorized item row: 26,000.00. |
| **Grand total** | \-20.00 \+ 65,500.00 \+ 100.00 \+ 26,000.00 \= $91,580.00 — matching the TOTAL row. |

| What this report is telling Halo Axis Halo Axis had $91,580.00 of taxable sales across All Dates on an accrual basis. Air Pod 3nd Gen alone is about 72% of that (65,500 of 91,580), so the taxable bill is concentrated in one product. Two small items of housekeeping stand out: a \-20.00 amount is sitting in the no-item bucket and would be cleaner assigned to a product, and a deleted item still carries $100.00 under Gadget — expected behavior, not an error. For filing, $91,580.00 is the taxable base to reconcile against the sales tax collected and report on the relevant state and local returns. |
| :---- |

# **11\. Reconciliation & Validation**

Because the report is the taxable sales base re-presented by product, it should tie to the other places that base appears — the sales tax liability and the return itself.

## **11.1 The key relationships**

| Taxable Sales (this report)  \=  Taxable base on the Sales Tax Liability report |
| :---: |
| **Taxable Sales  \+  Non-Taxable Sales  \=  Total Sales** |

Run for the same period and basis, the grand total here should equal the taxable sales shown on the Sales Tax Liability report and the taxable-sales figure entered on the return. The second relationship is a quick completeness check against total sales.

## **11.2 Common reasons figures might differ**

* The reports were run for different periods or on different bases (cash vs. accrual).

* An item’s tax status was changed after some sales were recorded, so history and current settings disagree.

* A customer’s exempt status, or an exemption certificate, was applied or removed mid-period.

* Income was posted by journal entry without a product or service, so it never registered as taxable sales.

* Rounding differences between the line-level base and tax calculated at the invoice or jurisdiction level.

| Reconciliation tip Start by confirming the period and basis match across the report, the liability report, and the return. Next, scan for items whose tax status looks wrong and for income entered without an item. Those few checks resolve the large majority of taxable-sales discrepancies before a filing goes out. |
| :---- |

# **12\. Use Cases & Business Scenarios**

The same report supports several recurring tasks for a US small or mid-sized business:

| Scenario | How the report helps |
| :---- | :---- |
| **Filing a sales tax return** | Supplies the taxable sales base for the period and jurisdiction the return covers. |
| **Reconciling to tax collected** | The taxable base is matched against the sales tax liability to confirm the two agree before filing. |
| **Separating taxable vs. exempt** | Isolates taxable revenue so exempt and resale sales can be supported separately in an audit. |
| **Surviving a sales tax audit** | Provides product-level backup that ties the return to source transactions. |
| **Finding mis-set tax status** | Unexpected items in or out of the taxable total reveal products or customers flagged incorrectly. |
| **Cleaning up data** | The no-item bucket and any negatives highlight lines to tidy before they affect a filing. |
| **Trend & forecasting** | “Compare to” and “Display columns by” show taxable sales over months or quarters. |
| **Multi-jurisdiction reporting** | Customer or location filters produce a taxable base per state, county, or city you report to. |

# **13\. Best Practices**

* Match the report’s period and basis to the return you are filing — a mismatch is the most common cause of a wrong base.

* Assign a product or service to every sales line so nothing lands in the unlabeled no-item bucket.

* Keep item and customer tax status accurate, and review it periodically as products and rules change.

* Reconcile taxable sales to the sales tax liability every filing period before submitting.

* Expect deleted items to appear with their historical sales — retain them rather than trying to remove the rows.

* Investigate negative lines (credits, refunds, discounts) to confirm they are correctly treated as taxable.

* Use categories consistently so subtotals stay meaningful across periods.

* Save a filing-aligned version per jurisdiction so each period is a one-click refresh.

* Keep exemption and resale certificates on file to support every sale you exclude as non-taxable.

# **14\. FAQ & Troubleshooting**

**Q.  Why is there a row with no product or service name?**

**A.**  Those are taxable amounts on sales lines that had no item assigned — often a discount or a credit entered without a product. Assign an item to keep the report clean. See Section 7.3.

**Q.  Why does a deleted item still appear?**

**A.**  Because it had taxable sales in the period. History is preserved so past periods stay complete, and the row is marked “(deleted).” The amount still counts.

**Q.  Why is an amount negative?**

**A.**  Credit memos, refund receipts, returns, and discounts on taxable sales reduce the base, so a row — or the no-item bucket — can be negative (for example, \-20.00).

**Q.  Does this include the sales tax I collected?**

**A.**  No. It shows the taxable sales base — the amount tax is calculated on — not the tax itself. Use the Sales Tax Liability report for tax collected.

**Q.  Cash or accrual — which should I use?**

**A.**  Match the basis you file sales tax on. Accrual counts sales when invoiced; cash counts them when paid. The example uses accrual.

**Q.  My total doesn’t match my sales tax return.**

**A.**  Confirm the period and basis match, check item and customer tax status, and look for income entered without an item. See Section 11\.

**Q.  Can I split the Total into months or by customer?**

**A.**  Yes — use “Display columns by” for periods, customers, classes, or locations, and “Compare to” to add a prior period.

**Q.  What is the difference between taxable and total sales?**

**A.**  Total sales includes exempt and non-taxable sales; taxable sales is only the portion subject to sales tax. Taxable \+ non-taxable \= total sales.

# **15\. Glossary**

| Term | Definition |
| :---- | :---- |
| **Accrual basis** | Recognizing sales when invoiced, regardless of payment. |
| **Cash basis** | Recognizing sales when payment is received. |
| **Category** | A grouping of products or services that produces a subtotal on the report. |
| **Credit memo** | A document that reduces what a customer owes; on taxable lines it lowers the taxable base. |
| **Exempt sale** | A sale not subject to sales tax — for example to an exempt customer or for resale. |
| **Jurisdiction** | A taxing authority (state, county, or city) a business reports and remits sales tax to. |
| **Non-taxable sales** | Sales not subject to sales tax; excluded from this report. |
| **Product / Service (item)** | The line item sold on a sales form; the report groups taxable amounts by it. |
| **Refund receipt** | A document recording money returned to a customer; reduces taxable sales on taxable lines. |
| **Sales receipt** | A sale paid at the time of purchase, recorded on one document. |
| **Sales tax** | Tax charged on taxable sales, set by state and local jurisdictions; not shown on this report. |
| **Sales tax liability** | The tax collected and owed to each jurisdiction; reported separately from the taxable base. |
| **Taxable sales** | The portion of sales subject to sales tax — the base this report summarizes. |
| **Tax status** | The taxable-or-exempt flag on an item or customer that decides what the report includes. |

*End of document  ·  Pilucent — Taxable Sales Summary Report Documentation  ·  v1.0*