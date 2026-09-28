  
**BALANZIFY**

Accounting & Bookkeeping Platform

**Inventory Valuation Summary**

**Report**

Product & Reporting Documentation

*Logic · Calculations · Filtering · Columns · Data Representation · Use Cases*

| Document | Inventory Valuation Summary — Functional Specification |
| :---- | :---- |
| **Module** | Reports → Inventory → Inventory Valuation Summary |
| **Audience** | Owners, bookkeepers, accountants, inventory & operations staff |
| **Version** | 1.0 |
| **Status** | Released |

**Table of Contents**

[**1\. Introduction & Overview	3**](#heading=)

[1.1 What the report answers	3](#heading=)

[1.2 Who uses it	3](#heading=)

[1.3 Where it sits in the inventory workflow	3](#heading=)

[**2\. Key Concepts & Terminology	5**](#heading=)

[**3\. Anatomy of the Report	6**](#heading=)

[3.1 The control strip	6](#heading=)

[3.2 The report header	6](#heading=)

[3.3 The data grid	6](#heading=)

[3.4 The footer	6](#heading=)

[**4\. Columns Explained	7**](#heading=)

[**5\. The Valuation Logic (Core Engine)	8**](#heading=)

[5.1 Step one — establish the as-of date	8](#heading=)

[5.2 Step two — determine the quantity on hand	8](#heading=)

[5.3 Step three — value the on-hand units at cost	8](#heading=)

[5.4 Step four — derive the calculated average	8](#heading=)

[5.5 A worked micro-example	8](#heading=)

[**6\. Calculation Methodology	10**](#heading=)

[6.1 Pass 1 — per item (each row)	10](#heading=)

[6.2 Pass 2 — the totals row	10](#heading=)

[**7\. What Data Appears on the Report	11**](#heading=)

[7.1 Only inventory items appear	11](#heading=)

[7.2 Transactions that change quantity and value	11](#heading=)

[7.3 On-hand, at a point in time	11](#heading=)

[7.4 When values look negative or odd	11](#heading=)

[7.5 Accounting basis	11](#heading=)

[**8\. Filtering & Customization	12**](#heading=)

[**9\. Data Representation & Formatting	13**](#heading=)

[**10\. Worked Example — Reading a Real Report	14**](#heading=)

[10.1 The report as displayed	14](#heading=)

[10.2 Reading each item	14](#heading=)

[10.3 Verifying the totals	14](#heading=)

[**11\. Reconciliation & Validation	16**](#heading=)

[11.1 The key relationship	16](#heading=)

[11.2 Common reasons they might differ	16](#heading=)

[**12\. Use Cases & Business Scenarios	17**](#heading=)

[**13\. Best Practices	18**](#heading=)

[**14\. FAQ & Troubleshooting	19**](#heading=)

[**15\. Glossary	20**](#heading=)

# **1\. Introduction & Overview**

The Inventory Valuation Summary Report in Balanzify gives you a clear, single-screen picture of how much your on-hand inventory is worth at cost. It shows one consolidated line per inventory item — the quantity you currently hold, the total value tied up in it, and the average cost of a single unit. Instead of adding up purchase costs by hand, you see the current book value of your stock at a glance.

The report connects your books and your shelves at the same time. The total it produces is the figure that backs the Inventory Asset line on your Balance Sheet, and the per-item breakdown tells you exactly where your money is sitting across products. It values inventory at cost — what you paid for the goods — not at the price you sell them for.

## **1.1 What the report answers**

A single Inventory Valuation Summary is designed to answer three questions at a glance:

* **How much stock do we hold?** Each item shows its quantity on hand, and the bottom row totals every unit.

* **What is it worth at cost?** The Asset Value column shows the cost value per item, and the total equals the inventory asset carried on the books.

* **What does a unit cost on average?** The Calc. Avg column divides value by quantity to give a representative per-unit cost.

## **1.2 Who uses it**

| Role | Why they rely on it |
| :---- | :---- |
| **Business owner / founder** | Sees how much cash is tied up in stock and which products hold the most value. |
| **Bookkeeper** | Reconciles the total to the Inventory Asset account and checks for data problems before close. |
| **Accountant / Controller** | Confirms the inventory asset figure for the financial statements and reviews cost movements. |
| **Inventory / Operations manager** | Monitors stock levels, spots overstock and slow movers, and watches unit-cost trends. |
| **Purchasing** | Uses on-hand quantity and average cost to inform reorder timing and price negotiations. |
| **Auditor / Reviewer** | Tests the existence and valuation of inventory as of a specific date. |

## **1.3 Where it sits in the inventory workflow**

Every time you purchase or receive stock, sell it, or adjust a quantity, Balanzify updates two things behind the scenes: the quantity on hand for the item, and the cost value held in the Inventory Asset account. The Inventory Valuation Summary is the reporting lens placed over that activity. It does not create or change any data — it reads the current on-hand quantities and their cost, and re-presents them per item. Because of this, the report is always only as accurate as the purchases, sales, and adjustments behind it.

| Summary vs. Detail Balanzify offers two related reports. The Inventory Valuation Summary (this document) shows one rolled-up line per item. The Inventory Valuation Detail report breaks the same figures down into the individual transactions — each purchase, sale, and adjustment — with a running quantity and value after every one. Whenever you need to see what makes up a number on the Summary, drill into the Detail. |
| :---- |

# **2\. Key Concepts & Terminology**

A few core ideas drive everything in this report. Getting comfortable with them makes the calculations and settings that follow easy to read.

| Term | Meaning in Balanzify |
| :---- | :---- |
| **Inventory item** | A product you buy and resell, for which Balanzify tracks quantity on hand and cost value. Only these items appear on the report. |
| **Quantity on hand (Qty)** | The number of units currently in stock as of the report’s as-of date. It can include decimals for items sold in fractional units. |
| **Cost vs. sales price** | The report values stock at cost — what you paid suppliers — not at the retail price you charge customers. |
| **Asset Value** | The total cost value of the on-hand units for an item. This is the amount sitting in the Inventory Asset account for that product. |
| **Costing method** | The rule that assigns cost to units as they are sold and to the units that remain (for example, FIFO or average cost). It determines the Asset Value. |
| **Calculated average (Calc. Avg)** | Asset Value divided by Quantity — a single representative cost per unit on hand. |
| **SKU** | Stock Keeping Unit: an optional code that identifies an item. It is blank when no SKU has been assigned. |
| **Inventory Asset account** | The Balance Sheet asset account that holds the cost of unsold inventory until it is sold. |
| **As-of date** | The point in time at which quantity and value are measured. Inventory value is always a snapshot at a moment, not a range. |

# **3\. Anatomy of the Report**

The screen is made up of a small control strip, a report header, the data grid, and a footer. Knowing each region makes the rest of this document easier to follow.

## **3.1 The control strip**

Running across the top of the report are the controls used to shape and share it:

* **Back to standard reports —** returns to the report list.

* **Report period —** chooses the date basis. “All Dates” values everything as of today; pick a date to value stock as it stood then.

* **Customize —** opens the full settings panel: filters, columns, sort, and header/footer options.

* **Save As —** stores your customized version as a reusable saved report.

* **Refresh, Email, Print, Export —** regenerate the figures, send the report, print it, or export it to a spreadsheet or PDF.

* **Compact and zoom —** toggle a denser layout and scale the on-screen size (for example, Compact | 100%). These affect display only, never the numbers.

## **3.2 The report header**

Centered above the grid, the header identifies exactly what you are looking at:

* **Company name** — the business the report belongs to (for example, Halo Axis).

* **Report title** — “Inventory Valuation Summary.”

* **Date basis** — the selected report period (for example, “All Dates”).

## **3.3 The data grid**

The body is a simple matrix. Each row is an inventory item; the columns are SKU, Qty, Asset Value, and Calc. Avg. The bottom row totals the quantity and the value down the page, and shows a blended average cost. A sort control on the Calc. Avg header lets you rank items by their per-unit cost.

## **3.4 The footer**

Below the grid, Balanzify stamps the exact date and time the report was generated, along with the time zone (for example, Wednesday, June 24, 2026 02:55 PM GMT+06:00). Because inventory value is a snapshot at a point in time, this timestamp matters — the same report run later can show different numbers if stock has moved. There is also an option to attach a note for context.

# **4\. Columns Explained**

The report shows the following columns from left to right. The item name occupies the first, unlabeled column, and a Total row closes the grid.

| Column | What it represents | How it is derived |
| :---- | :---- | :---: |
| **Item / Product** | The inventory item the line describes. One row per item that is tracked for quantity and value. | — |
| **SKU** | The item’s Stock Keeping Unit code, if one is assigned. Blank when none exists (as in the example). | From the item record |
| **Qty** | Quantity on hand as of the report date. Supports decimals for fractional units. | Units in − units out |
| **Asset Value** | The total cost value of that on-hand quantity — the amount held in Inventory Asset for the item. | Cost of units on hand |
| **Calc. Avg** | The average cost of a single unit on hand. | Asset Value ÷ Qty |
| **Total (row)** | Company-wide totals: all units, total inventory value, and a blended average cost. | See Section 6.2 |

| The total Calc. Avg is a weighted average The Calc. Avg on the Total row is not the average of the per-item averages. It is the total Asset Value divided by the total Quantity — a weighted average that reflects how many units sit behind each price. This is why a few high-volume, low-cost items pull the blended average toward their cost. Section 10 shows the arithmetic on real numbers. |
| :---- |

# **5\. The Valuation Logic (Core Engine)**

Strip everything else away and the report answers, for each product, two questions: how many units do we have on hand right now, and what did those specific units cost? Everything else is arithmetic on those two figures.

## **5.1 Step one — establish the as-of date**

Inventory value is always measured at a single point in time, called the as-of date. By default the report period is “All Dates,” which values stock as it stands today — the moment you run the report. Choosing an earlier date rebuilds the picture as it was on that day. This is why the footer timestamp matters: it records the moment the snapshot was taken.

## **5.2 Step two — determine the quantity on hand**

For each item, Balanzify nets every movement up to the as-of date — units brought in by purchases and positive adjustments, less units removed by sales and negative adjustments:

| Quantity on Hand  \=  Units In  −  Units Out |
| :---: |

## **5.3 Step three — value the on-hand units at cost**

Each unit carries the cost it was bought at, under the company’s costing method. The Asset Value is the cost of the units that are still on hand — not their sales price. Under an average-cost method this is the quantity multiplied by the moving average unit cost; under a first-in, first-out (FIFO) method it is the sum of the most recent cost layers that remain in stock. Either way, the report presents the resulting on-hand cost as the Asset Value.

| Cost, not price — and which costing method The report never uses the retail or sales price. It reflects what you paid. The costing method (commonly FIFO or average cost) decides how cost is assigned to the units sold versus those remaining, and therefore sets the Asset Value. The Calc. Avg column then simply divides that value by the quantity, so it reads as a clean per-unit figure regardless of which method produced the value. |
| :---- |

## **5.4 Step four — derive the calculated average**

With quantity and value in hand, the per-unit average is a single division:

| Calc. Avg  \=  Asset Value  ÷  Quantity |
| :---: |

When every unit of an item was bought at the same cost, the Calc. Avg equals that exact unit cost. When units were bought at different costs over time, it lands somewhere between them, weighted by how many were bought at each price.

## **5.5 A worked micro-example**

Suppose you buy 100 units at 5.00 each, then 100 more at 7.00 each, and later sell 50 units. You now hold 150 units. Under an average-cost method the average unit cost is 6.00, so the Asset Value is 150 × 6.00 \= 900.00 and the Calc. Avg is 900.00 ÷ 150 \= 6.00. (A FIFO method would value the remaining 150 units from the specific cost layers still in stock, but the report would still display Asset Value ÷ Quantity in the Calc. Avg column.)

# **6\. Calculation Methodology**

The report is built in two passes: first each item line, then the totals. Both are simple sums and divisions, which is what makes the report quick to verify by hand.

## **6.1 Pass 1 — per item (each row)**

1. Net all stock movements up to the as-of date to get the quantity on hand (Section 5.2).

2. Value the on-hand units at cost under the costing method to get the Asset Value (Section 5.3).

3. Divide value by quantity to get the Calc. Avg (Section 5.4).

## **6.2 Pass 2 — the totals row**

The bottom row consolidates every item:

* **Total Qty —** the sum of every item’s quantity on hand.

* **Total Asset Value —** the sum of every item’s Asset Value; this is the company-wide inventory asset.

* **Total Calc. Avg —** the total Asset Value divided by the total Qty — a weighted blended cost per unit.

| Total Calc. Avg  \=  Total Asset Value  ÷  Total Qty |
| ----- |
| **Why the total average is weighted** Averaging the per-item Calc. Avg figures would treat a product you hold one of the same as a product you hold thousands of. Dividing total value by total quantity instead weights each item by how many units it actually contributes — the only blended cost that ties back to the real inventory value. See the worked example in Section 10.3. |

# **7\. What Data Appears on the Report**

The report reads only inventory items and only their on-hand cost. Understanding what raises and lowers quantity and value makes the numbers predictable.

## **7.1 Only inventory items appear**

Service items, non-inventory items, and bundles do not appear, because Balanzify does not track a quantity or a cost value for them. Only products set up as inventory — with a tracked quantity on hand and an inventory asset account — show on this report.

## **7.2 Transactions that change quantity and value**

| Transaction type | Effect on Qty | Effect on Asset Value |
| :---- | :---: | :---: |
| **Purchase / bill / item receipt** | Increases | Increases |
| **Inventory starting / opening value** | Sets initial | Sets initial |
| **Sale / invoice / sales receipt** | Decreases | Decreases (at cost) |
| **Inventory quantity adjustment** | Increases or decreases | Adjusts to match |
| **Inventory value adjustment** | No change | Increases or decreases |
| **Customer or vendor return** | Adjusts | Adjusts |

## **7.3 On-hand, at a point in time**

The report shows the standing balance of quantity and value as of the chosen date — not a running history. Stock that has already been sold is gone from the count; what remains is what you can still sell. Run the report for a different date and the snapshot rebuilds for that day.

## **7.4 When values look negative or odd**

A few patterns signal a data issue rather than a normal balance, and are worth investigating:

* **Negative quantity —** more units were sold or removed than were on hand, usually because a sale was entered before its purchase, or stock was oversold.

* **Quantity with no value, or value with no quantity —** often points to a cost layer that was not recorded, or an adjustment posted to one side only.

* **A sudden jump in Calc. Avg —** can reveal a cost entered with a typo or a mis-keyed quantity on a purchase.

## **7.5 Accounting basis**

Inventory is reported at cost, and the Asset Value is built from the actual item transactions — purchases, sales, and adjustments — rather than from a cash-versus-accrual toggle. The total therefore reconciles to the Inventory Asset account on the Balance Sheet for the same date (see Section 11).

# **8\. Filtering & Customization**

Everything about the report’s shape can be adjusted from the Customize panel. The most important settings are below; any combination can be saved as a named report for reuse.

| Setting | What it controls | Default / example |
| :---- | :---- | :---: |
| **Report period (as-of date)** | The point in time the snapshot is taken. “All Dates” values stock as of today. | All Dates |
| **Item / product filter** | Limit the report to one product, a category, or all inventory items. | All |
| **Columns** | Show or hide columns such as SKU, Qty, Asset Value, and Calc. Avg. | All shown |
| **Sort** | Order the rows — for example, by Calc. Avg, by value, or by name. | By item |
| **Layout & zoom** | Switch between Compact and full layouts and scale the on-screen view. | Compact | 100% |
| **Costing method** | Set on the item or company; determines how cost is assigned and therefore the Asset Value. | Per setup |

| The as-of date is the biggest lever Changing the report date moves both the quantity and the value at once, because it re-nets every transaction up to that day. Two copies of the report for different dates can legitimately differ even with no settings changed. When comparing against another report or the Balance Sheet, always confirm both use the same date first. |
| :---- |

# **9\. Data Representation & Formatting**

How the figures are displayed follows consistent conventions so the report reads cleanly at a glance.

| Convention | How it appears |
| :---- | :---- |
| **Quantity format** | Shown with two decimals to support fractional units (for example, 572.00). |
| **Asset Value** | Uses thousands separators and two decimals (for example, 228,950.00); the total carries the currency symbol ($327,950.00). |
| **Calc. Avg** | Shown with two decimals (for example, 400.26); the total carries the currency symbol ($488.75). |
| **SKU** | Plain text from the item record; left blank when no SKU is assigned, as in the example. |
| **Totals** | The bottom Total row is emphasized in bold and clearly separated from the item rows. |
| **Negative / unusual values** | Shown with a leading minus sign and may appear in red; they usually flag a data issue (Section 7.4). |
| **Sorting** | The Calc. Avg header includes a sort control to rank items by per-unit cost, highest or lowest first. |
| **Compact & zoom** | Compact tightens spacing; zoom scales the on-screen view. Both are display-only and never change the numbers. |
| **Export & share** | The report can be refreshed, emailed, printed, or exported to spreadsheet or PDF for distribution. |

# **10\. Worked Example — Reading a Real Report**

The example below is an Inventory Valuation Summary for a company called Halo Axis, run for All Dates as of June 24, 2026\. We will reproduce it exactly, then walk through every number so the logic in Sections 5 and 6 becomes concrete.

## **10.1 The report as displayed**

|  | SKU | Qty | Asset Value | Calc. Avg |
| :---- | :---: | ----: | ----: | ----: |
| **Air Pod 3nd Gen** |  | 572.00 | 228,950.00 | 400.26 |
| **Galaxy S25 Ultra 256GB** |  | 99.00 | 99,000.00 | 1,000.00 |
| **TOTAL** |  | **671.00** | **$327,950.00** | **$488.75** |

## **10.2 Reading each item**

**Air Pod 3nd Gen.** There are 572 units on hand, carrying a total cost of 228,950.00. Dividing the value by the quantity gives a Calc. Avg of 228,950.00 ÷ 572 \= 400.26 per unit. No SKU has been assigned, so that column is blank. Although the per-unit cost is the lower of the two products, the large quantity makes this the bigger position by value.

**Galaxy S25 Ultra 256GB.** There are 99 units on hand worth 99,000.00, so the Calc. Avg is 99,000.00 ÷ 99 \= exactly 1,000.00 per unit — a round figure, which tells us every unit is carried at the same 1,000.00 cost. This product is far more expensive per unit, but with fewer units it holds less total value than the AirPods.

## **10.3 Verifying the totals**

The bottom row can be reproduced exactly using the two-pass method:

| Figure | How it is reached |
| :---- | :---- |
| **Total Qty** | 572.00 \+ 99.00 \= 671.00 units. |
| **Total Asset Value** | 228,950.00 \+ 99,000.00 \= $327,950.00. |
| **Total Calc. Avg** | Total value ÷ total quantity: 327,950.00 ÷ 671 \= $488.75. |
| **Not the average of averages** | (400.26 \+ 1,000.00) ÷ 2 \= 700.13, which is wrong — the report uses the weighted figure, $488.75. |
| **Cross-check** | Each item’s Calc. Avg × its Qty returns its Asset Value (e.g., 400.26 × 572 ≈ 228,950), confirming the columns are consistent. |

| What this report is telling Halo Axis Halo Axis is holding $327,950.00 of inventory at cost across two products. By value, the AirPods make up roughly 70% of the stock (228,950 of 327,950) even though they cost far less per unit — simply because there are many more of them. The Galaxy units are high-value but low-quantity. The blended cost of a unit across the whole catalog is $488.75. If the goal were to free up cash tied in stock, the AirPod position is where most of it sits and would be the first place to look. |
| :---- |

# **11\. Reconciliation & Validation**

Because the report is just the inventory asset re-presented item by item, its total Asset Value should tie back to the Inventory Asset account reported elsewhere in Balanzify.

## **11.1 The key relationship**

| Total Asset Value  \=  Inventory Asset on the Balance Sheet |
| :---: |

When the Inventory Valuation Summary is run for the same date as the Balance Sheet, the total Asset Value should equal the Inventory Asset line. Matching these two figures is a standard period-end control.

## **11.2 Common reasons they might differ**

* The two reports were run for different dates — inventory value is a point-in-time snapshot.

* A journal entry posted directly to the Inventory Asset account, bypassing item transactions, so it moves the Balance Sheet but no item row.

* Inventory purchases were recorded to an expense or cost-of-goods account instead of the inventory item, so the value never entered the asset.

* More than one inventory asset account exists and the report was filtered to only one of them.

* A transaction is mid-entry or not fully posted, leaving the item records and the general ledger temporarily out of step.

| Reconciliation tip If the figures diverge, first confirm both reports use the same date. Next, look for journal entries to the Inventory Asset account that did not go through an item, and confirm that inventory purchases were booked to the item rather than straight to an expense. These checks resolve the large majority of inventory reconciliation differences. |
| :---- |

# **12\. Use Cases & Business Scenarios**

The same report supports several day-to-day and periodic decisions:

| Scenario | How the report helps |
| :---- | :---- |
| **Period-end financial statements** | Supplies the inventory asset figure that appears on the Balance Sheet at close. |
| **Reconciling inventory** | The total is matched to the Inventory Asset account to confirm the books and the stock agree. |
| **Working-capital management** | Shows how much cash is tied up in stock, and in which products, so it can be managed down. |
| **Concentration & overstock** | Highlights items that hold a disproportionate share of value or sit in large quantities. |
| **Pricing & margin** | The Calc. Avg per unit is the cost floor for pricing decisions and gross-margin analysis. |
| **Insurance & financing** | Provides a defensible at-cost inventory value for coverage limits or loans secured by stock. |
| **Audit & review** | Demonstrates the existence and valuation of inventory as of a chosen date. |
| **Data-quality checks** | Negative quantities and value/quantity mismatches surface entry errors before they reach the statements. |

# **13\. Best Practices**

* Reconcile the total Asset Value to the Inventory Asset account at every period close.

* Always note the as-of date — inventory value is a snapshot, and the same report on another day can differ.

* Record inventory purchases to the inventory item, never straight to an expense, so value flows into the asset correctly.

* Investigate negative quantities promptly; they distort value and usually signal an oversell or out-of-order entry.

* Watch the Calc. Avg for sudden jumps — they often reveal a mis-keyed cost or quantity on a purchase.

* Keep item costs and starting values accurate; the report is only as good as the cost data behind it.

* Assign SKUs to items for cleaner identification (the example report has none).

* Use the Inventory Valuation Detail report to explain any figure on the Summary.

* Run the report on a regular cadence and at period end so trends and errors surface early.

# **14\. FAQ & Troubleshooting**

**Q.  A product I sell isn’t on the report. Why?**

**A.**  It is most likely a service or non-inventory item, or an item you do not track quantity for. Only inventory-type items with a tracked quantity and value appear here.

**Q.  The SKU column is blank. Is that a problem?**

**A.**  No. SKU is optional. It is blank because no SKU has been assigned to the item — exactly as in the Halo Axis example. Add a SKU on the item record for easier identification.

**Q.  Why isn’t the total Calc. Avg the average of the two item averages?**

**A.**  Because it is a weighted average: total Asset Value divided by total Qty. Averaging 400.26 and 1,000.00 would ignore how many units sit behind each. See Section 10.3.

**Q.  A quantity is negative. What does that mean?**

**A.**  You have recorded more units sold or removed than were on hand — often a sale entered before its purchase, or oversold stock. Fix the underlying transactions; negatives distort the value.

**Q.  Does this report show the retail or sales value of my stock?**

**A.**  No. It values inventory at cost — what you paid. To see expected sales value you would use a different report.

**Q.  My total doesn’t match the inventory on the Balance Sheet.**

**A.**  Check that both use the same date, look for journal entries posted straight to the Inventory Asset account, and confirm purchases were booked to the item rather than an expense. See Section 11\.

**Q.  The numbers changed and I didn’t buy or sell anything today.**

**A.**  Inventory value is a point-in-time snapshot. A moved as-of date, a later transaction, or a backdated entry can all change the standing balance.

**Q.  Can I see what my inventory was worth on a past date?**

**A.**  Yes. Set the report period to that date and the report rebuilds quantity and value as they stood then.

# **15\. Glossary**

| Term | Definition |
| :---- | :---- |
| **As-of date** | The point in time at which quantity and value are measured; inventory value is always a snapshot. |
| **Asset Value** | The total cost value of an item’s on-hand units, held in the Inventory Asset account. |
| **Average cost** | A costing method that values units at a moving average of what they cost. |
| **Calculated average (Calc. Avg)** | Asset Value divided by Quantity; the average cost of a unit on hand. |
| **Costing method** | The rule (for example, FIFO or average cost) that assigns cost to units sold and remaining. |
| **FIFO** | First-in, first-out: the earliest-purchased units are treated as sold first, leaving the most recent costs in stock. |
| **Inventory Asset account** | The Balance Sheet asset account holding the cost of unsold inventory. |
| **Inventory item** | A product tracked for quantity on hand and cost value; only these appear on the report. |
| **Quantity on hand (Qty)** | Units currently in stock as of the report date. |
| **SKU** | Stock Keeping Unit — an optional code identifying an item. |
| **Unit cost** | What a single unit of an item cost to buy. |
| **Inventory valuation** | The process of placing a cost value on the stock a business holds. |

*End of document  ·  Balanzify — Inventory Valuation Summary Report Documentation  ·  v1.0*