

| PILUCENT   ·   PRODUCT DOCUMENTATION Inventory Valuation Detail Report Logic · Calculations · Filtering · Columns · Data Representation · Use Cases |
| :---- |

This guide explains exactly how Pilucent builds the Inventory Valuation Detail Report. It walks through every column, the formulas behind each figure, how each transaction moves quantity and value in and out of inventory, the costing method that values it, the filtering and customization options available to you, and the day-to-day decisions the report is designed to support. It is written for business owners, bookkeepers, accountants, and anyone on the finance team who needs to understand what the company holds in stock and what it is worth.

**Module:**  Inventory · Reporting        **Report type:**  Detail        **Version:**  1.0

Audience: Finance, Accounting & Bookkeeping teams

Last updated: June 2026

**Contents**

**1  Introduction**3

1.1  About this guide3

1.2  What the Inventory Valuation Detail Report is3

1.3  Why it matters3

**2  Key concepts and terminology**4

**3  How to read the report**4

3.1  The regions of the report4

3.2  Product groups and running balances5

**4  Column reference**5

**5  Valuation logic: how stock is costed**6

5.1  The costing method (FIFO)6

5.2  The running balances6

5.3  The per-line rule7

5.4  Quantity-only, value-only, and negative stock7

**6  Calculations**7

**7  Report period and date settings**8

**8  Filtering and customization**8

8.1  The Customize panel8

8.2  Columns you can add9

**9  Data representation and formatting**9

**10  Transaction types included**9

**11  Worked example: the sample report**10

11.1  The data10

11.2  How the key numbers are derived13

11.3  Reconciling to the Balance Sheet13

**12  Common use cases**13

**13  Best practices**14

**14  FAQ and troubleshooting**14

**15  Quick reference (cheat sheet)**15

# **1  Introduction**

## **1.1  About this guide**

Pilucent reports are most useful when you know precisely what each number means and where it comes from. This document removes the guesswork from the Inventory Valuation Detail Report. By the end of it you should be able to read any line on the report with confidence, reproduce every total by hand, and adjust the report so it answers the specific question in front of you — whether that is “how did this item’s value change over time?”, “why is my stock worth this much?”, or “does my inventory tie out to the Balance Sheet?”

## **1.2  What the Inventory Valuation Detail Report is**

The Inventory Valuation Detail Report is a transaction-by-transaction ledger of every movement in and out of each **inventory item** you track. For each product it lists, in date order, every purchase, sale, return, and adjustment — showing how many units moved, at what cost, and how the running **quantity on hand** and **asset value** changed after each one. Instead of a single stock figure, you see the full history behind it.

The word **Detail** is the important part. Pilucent offers two closely related reports built from the same data:

* **Inventory Valuation Summary —** collapses everything into one row per item — ending quantity on hand, asset value, and average cost. It answers “what do I hold, and what is it worth?”

* **Inventory Valuation Detail (this report) —** expands those balances into every underlying transaction. It answers “exactly which movements built up that quantity and value.”

Use the Summary for a quick stock-on-hand snapshot and the Detail when you need to trace, verify, or explain how an item reached its current value.

## **1.3  Why it matters**

* It shows what you hold in stock and what it is worth, item by item and in total.

* It lets you trace every change to an item’s quantity and value, so nothing about your inventory is a black box.

* It surfaces problems early — negative quantities on hand, purchases booked as plain expenses, or values that look wrong.

* It explains your Cost of Goods Sold: each sale relieves inventory at cost, and you can see exactly which cost left the asset.

* It supports month-end close: the report’s total asset value should reconcile to the Inventory asset account on your Balance Sheet.

| At a glance Report family — Detail — one row per inventory transaction. Source — Every transaction that affects an inventory item. Shows — Quantity moved, cost rate, value moved, and the running quantity on hand and asset value. Default grouping — By Product/Service, with a subtotal per item. Default sort — Transaction date within each item, oldest first. Costing method — FIFO — outbound units are relieved at the cost of the oldest stock on hand. Key figure — Asset value \= the running value of stock on hand after each transaction. |
| :---- |

# **2  Key concepts and terminology**

A handful of terms appear throughout the report and this guide. Skim these once and the rest of the document reads easily.

| Term | What it means |
| :---- | :---- |
| **Inventory item** | A product you buy and sell and whose quantity and value Pilucent tracks (a “Product/Service” of type Inventory). |
| **Quantity on hand** | The running number of units in stock after a transaction — a cumulative balance, not a single line’s amount. |
| **Rate** | The per-unit cost applied on a line. On purchases it is what you paid; on sales it is the cost of the units being relieved. |
| **Inventory cost** | The value a single transaction adds to or removes from inventory — positive when stock comes in, negative when it goes out. |
| **Asset value** | The running total value of stock on hand after a transaction — the inventory asset balance up to that point. |
| **FIFO** | First-In, First-Out — the costing method that relieves the oldest units first when stock is sold or removed. |
| **COGS** | Cost of Goods Sold — the cost that leaves inventory when an item is sold; it appears here as the negative Inventory cost on sale lines. |
| **Starting value** | The opening quantity and value recorded when an item is first set up (transaction type “Inventory Starting Value”). |
| **Quantity adjustment** | A manual correction to units on hand (for shrinkage, damage, or a recount) that can be positive or negative. |
| **Report period** | The date setting that controls which transactions are listed; “All Dates” shows an item’s full history. |

# **3  How to read the report**

## **3.1  The regions of the report**

From top to bottom, the report is organized into a few predictable regions. Knowing what each one does makes the whole report easy to scan.

| Region | Where it is | What it does |
| :---- | :---- | :---- |
| **Report title** | Top, centered | Names the report — “Inventory Valuation Detail.” |
| **Report period** | Top-left control | Sets the date range for the report (see Section 7). “All Dates” is the usual choice. |
| **Toolbar** | Top-right icons | View/zoom, refresh, email, print, and export (spreadsheet or PDF). |
| **Column headers** | Below the title | Label each column; the small arrows sort rows within each item group. |
| **Product group header** | Shaded row with a count | Starts an item’s section, e.g. “Air Pod 3nd Gen (45).” The number is the count of transactions for that item. |
| **Detail rows** | Under each group | One inventory transaction per line — the heart of the report. |
| **Group subtotal** | “Total for …” row | Shows the item’s ending quantity, total inventory cost, and ending asset value. |
| **Grand total** | “TOTAL” row at the bottom | Sums every item into your overall inventory quantity and asset value. |

## **3.2  Product groups and running balances**

Each product is shown as its own block of transactions, listed in date order. Two columns carry a running balance that updates line by line: Quantity on hand (how many units are in stock after that transaction) and Asset value (what the stock is worth after it). Read a group from top to bottom and you watch the item’s stock and value build up and draw down over its whole history — which is why the period is normally left on All Dates, so the running balances start from the very first transaction.

# **4  Column reference**

Below is every default column on the report, what it shows, and where its value comes from. You can add, remove, and reorder columns under Customize (Section 8).

| Column | What it shows | Where it comes from / how it is calculated |
| :---- | :---- | :---- |
| **Product/Service** | The inventory item the line belongs to. | The item name from your Products and Services list. Rows are grouped under it. |
| **Transaction date** | When the transaction took effect. | Taken from the transaction. Lines are sorted by this date within each item so the running balances make sense. |
| **Transaction type** | The kind of movement — sale, purchase, return, or adjustment. | Tells you why stock moved: Invoice/Sales Receipt (out), Bill/Check/Expense (in), Credit Memo/Refund (in), Vendor Credit (out or value-only), Inventory Qty Adjust (either), or Inventory Starting Value (opening). |
| **Num** | The reference or document number. | The invoice/check/adjustment number, or “START” for an opening balance. Blank where none applies (often bills, expenses, and vendor credits). |
| **Name** | The customer or vendor on the transaction. | The contact attached to the source transaction. Blank for starting values and quantity adjustments. |
| **Qty** | Units this transaction added or removed. | Positive when stock comes in, negative when it goes out. The running Quantity on hand changes by this amount. |
| **Rate** | The per-unit cost used on the line. | On inbound lines, the purchase cost. On outbound lines, the FIFO cost of the units being relieved — which is why the same item can leave at different rates. |
| **Inventory cost** | The value this transaction added to or removed from inventory. | Generally Qty × Rate, signed to match Qty. A value-only adjustment can post an Inventory cost with a Qty of 0\. |
| **Qty on hand** | Running units in stock after the line. | Previous Quantity on hand \+ this line’s Qty. Can go negative if stock is sold before it is recorded as received. |
| **Asset value** | Running value of stock on hand after the line. | Previous Asset value \+ this line’s Inventory cost. This is the inventory asset balance up to that point. |

# **5  Valuation logic: how stock is costed**

## **5.1  The costing method (FIFO)**

Pilucent values inventory using **FIFO — First In, First Out**. The idea is simple: when you sell or remove stock, you relieve the **oldest** units first. Each item keeps an ordered set of cost “layers” as you buy stock; an outbound transaction consumes those layers from the oldest forward, and the Rate shown on the line is the cost of the layer being used. That is why the same product can leave inventory at different rates on different days — in the sample, Air Pod units go out at 400, then later at 410 and 450 as the early, cheaper layers run out.

| Buy 10 @ 400, then 10 @ 450    →  layers: \[10 @ 400\] \[10 @ 450\]   Sell 12 units under FIFO:    • 10 relieved from the 400 layer   →  4,000    •  2 relieved from the 450 layer   →    900    layers left: \[8 @ 450\] |
| :---- |

## **5.2  The running balances**

Two columns are cumulative, recomputed on every line, which is what makes the report a true ledger:

| Qty on hand   \=  previous Qty on hand   \+  this line's Qty Asset value   \=  previous Asset value   \+  this line's Inventory cost |
| :---- |

Because both start from zero before the item’s first transaction, the final Asset value on the last line is simply the sum of every Inventory cost in the group — the value of the stock you still hold.

## **5.3  The per-line rule**

For an ordinary movement, the value that flows in or out is the quantity times the rate, signed to follow the quantity:

| Inventory cost  \=  Qty  ×  Rate            (sign follows Qty)   in   (Qty \> 0):  Inventory cost is positive  → Asset value rises out  (Qty \< 0):  Inventory cost is negative  → Asset value falls |
| :---- |

## **5.4  Quantity-only, value-only, and negative stock**

A few lines do not follow the plain Qty × Rate pattern, and the report shows them faithfully:

* **Value-only adjustments —** some lines carry a Qty of 0 but still post an Inventory cost — a pure value adjustment that re-states what the stock on hand is worth without changing how many units there are. In the sample, several Air Pod and Galaxy “Vendor Credit” lines show Qty 0.00 with a non-zero Inventory cost.

* **Quantity-only moves —** an Inventory Qty Adjust can change the units on hand (for a recount, breakage, or shrinkage) and move value accordingly.

* **Negative quantity on hand —** if stock is sold or removed before the matching purchase is recorded, Quantity on hand can dip below zero — the Air Pod line dated 06/25/2025 briefly shows −1.00 on hand. It is not blocked, but it is a flag worth investigating (usually a missing or mis-dated purchase).

# **6  Calculations**

Every figure on the report can be reproduced with a few simple rules.

**6.1  Inventory cost (per line).**  For a normal movement, Inventory cost \= Qty × Rate, taking the sign of the quantity. A purchase of 3 units at 400 posts \+1,200; a sale of 1 unit relieved at 400 posts −400. Value-only adjustments are the exception: they post an Inventory cost directly while Qty stays 0\.

**6.2  Quantity on hand (running).**  Quantity on hand \= previous Quantity on hand \+ this line’s Qty. In the Air Pod group it opens at 10, falls to 9 then 8 after the first two sales, climbs back to 10 after a 2-unit return, and so on down the column.

**6.3  Asset value (running).**  Asset value \= previous Asset value \+ this line’s Inventory cost. Air Pod opens at 4,000; the first sale (−400) takes it to 3,600, the next (−400) to 3,200, and a 2-unit credit memo (+800) back to 4,000 — each line simply carries the balance forward.

**6.4  Subtotals and the grand total.**  Each item’s “Total for …” row shows three figures: the net Qty (which equals the ending Quantity on hand), the total Inventory cost, and the ending Asset value. Because every value movement is summed from a zero start, the total Inventory cost equals the ending Asset value — both read 228,950.00 for Air Pod and 99,000.00 for Galaxy. The “TOTAL” row adds the items together: Qty 572 \+ 99 \= 671, and Asset value 228,950.00 \+ 99,000.00 \= 327,950.00.

# **7  Report period and date settings**

The Report period control (top-left) sets which transactions the report lists. The sample is set to All Dates. The dropdown offers a standard set of ready-made ranges plus a custom option:

| Option | What it does |
| :---- | :---- |
| **All Dates** | Lists every transaction for each item from its inception. The natural choice here, because Quantity on hand and Asset value are running balances that only make sense from the first movement. |
| **Custom dates** | You pick a specific From/To range — useful for isolating a period’s activity. The opening running balance still reflects everything before the range. |
| **Today** | Limits to today’s transactions. |
| **This week / to date** | The current calendar week — the whole week, or only up to today. |
| **This fiscal week** | The current week on your fiscal calendar. |
| **This month / to date** | The current month — whole month, or up to today. |
| **This quarter / This fiscal quarter** | The current (calendar or fiscal) quarter; “to date” variants stop at today. |
| **This year / This fiscal year** | The current (calendar or fiscal) year; “to date” variants stop at today. |
| **Last week / month / quarter / year** | The matching prior period (further down the list). |

The dropdown scrolls, so the list continues with the “…to date,” fiscal, and “Last …” variants. Because this report is a running ledger, narrowing the period only changes which lines are displayed; the valuation itself is always built up in date order from each item’s very first transaction.

# **8  Filtering and customization**

## **8.1  The Customize panel**

The Customize button opens a panel where you reshape the report. The most useful controls are grouped here:

* **General —** report period, accounting method (Accrual or Cash), and number format — show or hide cents, divide by 1,000, hide zero amounts, and show negatives in red or in parentheses.

* **Rows / Columns —** choose which columns appear and in what order, toggle the grouping by Product/Service, and set the sort column and direction.

* **Filter —** narrow the report by Product/Service, Transaction type, or Name (the customer/vendor on the line) — for example, to inspect a single item or only the quantity adjustments.

* **Header / Footer —** control the company name, report title, the prepared date/time, and page numbers shown on the printed report.

Once a report looks the way you want, use Save As to keep it as a custom report you can reopen with one click.

## **8.2  Columns you can add**

Beyond the defaults, you can surface extra columns when you need more context. Common additions include:

* Memo / Description (the line note on the source transaction)

* Account (the inventory asset account affected)

* Sales price or Amount (the selling side, when you want price alongside cost)

* Class / Location (if you track them)

* Currency and exchange rate (for multi-currency books)

* Created date, Last modified, and Last modified by (for audit trails)

# **9  Data representation and formatting**

How the report displays its data is just as important as the numbers themselves:

* **Grouping —** rows are grouped by Product/Service; each item carries a header (with a transaction count) and a subtotal.

* **Sorting —** the arrows in each column header sort rows within each item. The default is Transaction date, ascending — essential here, since the running Quantity on hand and Asset value are calculated in that order.

* **Signs and emphasis —** inbound movements are positive and outbound negative; via number format, negatives can be shown in red or wrapped in parentheses. Subtotals and the grand total are bold and separated by a rule line.

* **Collapse / expand —** the chevron beside each item header collapses that item down to just its subtotal, which is handy when you only care about ending values.

* **Zoom and density —** the “Compact | 100%” control adjusts zoom and the on-screen density.

* **Share and export —** the toolbar lets you refresh, email, print, or export the report to a spreadsheet or PDF, preserving the grouping and totals.

# **10  Transaction types included**

Any transaction that changes the quantity or value of an inventory item appears here. The ones in the sample, and what each does to stock:

* **Inventory Starting Value —** the opening balance recorded when an item is first set up (Num “START”). Sets the initial Quantity on hand and Asset value. Inbound (positive).

* **Bill / Check / Expense —** three ways to buy stock from a vendor. Each adds units and value. Inbound (positive).

* **Vendor Credit —** a return to a vendor or a cost adjustment. Usually removes units and value (outbound), but can be value-only with a Qty of 0\.

* **Invoice / Sales Receipt —** a sale to a customer — on terms (Invoice) or paid at the point of sale (Sales Receipt). Both relieve stock at FIFO cost. Outbound (negative).

* **Credit Memo / Refund —** a customer return that brings stock back in. Inbound (positive).

* **Inventory Qty Adjust —** a manual quantity correction for shrinkage, damage, or a recount. Can be inbound or outbound.

Transactions that don’t touch an inventory item — service sales, non-inventory purchases, and the like — never appear here. If you expected a transaction and don’t see it, it most likely did not move an inventory item (for example, a purchase booked to a plain expense account rather than to the item).

# **11  Worked example: the sample report**

## **11.1  The data**

Below is a faithful recreation of the full sample Inventory Valuation Detail Report, run on All Dates. It tracks two items — Air Pod 3nd Gen (45 transactions) and Galaxy S25 Ultra 256GB (18 transactions) — each grouped with its own subtotal, followed by the grand total. Read each group top-to-bottom and watch the Quantity on hand and Asset value columns carry forward line by line.

| Product/Service | Transaction date | Transaction type | Num | Name | Qty | Rate | Inventory cost | Qty on hand | Asset value |
| :---- | :---- | :---- | :---- | :---- | ----: | ----- | ----: | ----- | ----: |
| **Air Pod 3nd Gen (45)** |  |  |  |  |  |  |  |  |  |
| Air Pod 3nd Gen | 04/13/2025 | Inventory Starting Value | START |  | 10.00 | 400.00 | 4,000.00 | 10.00 | 4,000.00 |
| Air Pod 3nd Gen | 04/20/2025 | Invoice | 1002 | Nazirul | \-1.00 | 400.00 | \-400.00 | 9.00 | 3,600.00 |
| Air Pod 3nd Gen | 04/22/2025 | Invoice | 1003 | JumaTechs | \-1.00 | 400.00 | \-400.00 | 8.00 | 3,200.00 |
| Air Pod 3nd Gen | 04/22/2025 | Credit Memo | 1006 | Star Tech | 2.00 | 400.00 | 800.00 | 10.00 | 4,000.00 |
| Air Pod 3nd Gen | 04/22/2025 | Refund | 1007 | Mukta | 2.00 | 400.00 | 800.00 | 12.00 | 4,800.00 |
| Air Pod 3nd Gen | 04/23/2025 | Invoice | 1009 | France | \-2.00 | 400.00 | \-800.00 | 10.00 | 4,000.00 |
| Air Pod 3nd Gen | 04/23/2025 | Expense |  | Binary Burst | 1.00 | 400.00 | 400.00 | 11.00 | 4,400.00 |
| Air Pod 3nd Gen | 04/23/2025 | Check | 2 | JumaTechs | 3.00 | 400.00 | 1,200.00 | 14.00 | 5,600.00 |
| Air Pod 3nd Gen | 04/23/2025 | Vendor Credit |  | Unimart | \-2.00 | 400.00 | \-800.00 | 12.00 | 4,800.00 |
| Air Pod 3nd Gen | 04/23/2025 | Bill |  | Unimart | 1.00 | 400.00 | 400.00 | 13.00 | 5,200.00 |
| Air Pod 3nd Gen | 04/25/2025 | Vendor Credit |  | Kaniz | \-1.00 | 400.00 | \-400.00 | 12.00 | 4,800.00 |
| Air Pod 3nd Gen | 04/25/2025 | Bill |  | Kaniz | 3.00 | 400.00 | 1,200.00 | 15.00 | 6,000.00 |
| Air Pod 3nd Gen | 04/30/2025 | Inventory Qty Adjust | 3 |  | \-3.00 | 400.00 | \-1,200.00 | 12.00 | 4,800.00 |
| Air Pod 3nd Gen | 05/05/2025 | Invoice | 1012 | France | \-2.00 | 400.00 | \-800.00 | 10.00 | 4,000.00 |
| Air Pod 3nd Gen | 05/05/2025 | Invoice | 1012 | France | \-2.00 | 400.00 | \-800.00 | 8.00 | 3,200.00 |
| Air Pod 3nd Gen | 06/03/2025 | Invoice | 1015 | Suzon Rana | \-2.00 | 400.00 | \-800.00 | 6.00 | 2,400.00 |
| Air Pod 3nd Gen | 06/10/2025 | Expense |  | Ragib | 10.00 | 410.00 | 4,100.00 | 16.00 | 6,500.00 |
| Air Pod 3nd Gen | 06/12/2025 | Invoice | 1016 | France | \-1.00 | 400.00 | \-400.00 | 15.00 | 6,100.00 |
| Air Pod 3nd Gen | 06/14/2025 | Expense |  | Ragib | 10.00 | 450.00 | 4,500.00 | 25.00 | 10,600.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Kaniz | \-1.00 | 400.00 | \-400.00 | 24.00 | 10,200.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Kaniz | 0.00 | \-50.00 | \-50.00 | 24.00 | 10,150.00 |
| Air Pod 3nd Gen | 06/16/2025 | Expense |  | Binary Burst | 10.00 | 450.00 | 4,500.00 | 34.00 | 14,650.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Binary Burst | \-5.00 | 450.00 | \-2,250.00 | 29.00 | 12,400.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Binary Burst | 0.00 | 40.00 | 200.00 | 29.00 | 12,600.00 |
| Air Pod 3nd Gen | 06/16/2025 | Invoice | 1017 | France | \-5.00 | 450.00 | \-2,250.00 | 24.00 | 10,350.00 |
| Air Pod 3nd Gen | 06/16/2025 | Invoice | 1018 | Suzon Rana | \-4.00 | 450.00 | \-1,800.00 | 20.00 | 8,550.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Ragib | \-10.00 | 410.00 | \-4,100.00 | 10.00 | 4,450.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Ragib | 0.00 | 10.00 | 10.00 | 10.00 | 4,460.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Ragib | 0.00 | 10.00 | 10.00 | 10.00 | 4,470.00 |
| Air Pod 3nd Gen | 06/16/2025 | Vendor Credit |  | Ragib | 0.00 | 10.00 | 30.00 | 10.00 | 4,500.00 |
| Air Pod 3nd Gen | 06/16/2025 | Invoice | 1019 | JumaTechs | \-5.00 | 410.00 | \-2,050.00 | 5.00 | 2,450.00 |
| Air Pod 3nd Gen | 06/16/2025 | Invoice | 1019 | JumaTechs | \-5.00 | 450.00 | \-2,250.00 | 0.00 | 200.00 |
| Air Pod 3nd Gen | 06/25/2025 | Vendor Credit |  | Binary Burst | \-1.00 | 400.00 | \-400.00 | \-1.00 | \-200.00 |
| Air Pod 3nd Gen | 06/25/2025 | Vendor Credit |  | Binary Burst | 0.00 | \-50.00 | \-50.00 | \-1.00 | \-250.00 |
| Air Pod 3nd Gen | 06/25/2025 | Bill |  | Unimart | 1000.00 | 400.00 | 400,000.00 | 999.00 | 399,750.00 |
| Air Pod 3nd Gen | 06/25/2025 | Vendor Credit |  | Unimart | \-10.00 | 400.00 | \-4,000.00 | 989.00 | 395,750.00 |
| Air Pod 3nd Gen | 07/02/2025 | Sales Receipt | 1022 | France | \-100.00 | 400.00 | \-40,000.00 | 889.00 | 355,750.00 |
| Air Pod 3nd Gen | 02/13/2026 | Inventory Qty Adjust | 8 |  | 10.00 | 400.00 | 4,000.00 | 899.00 | 359,750.00 |
| Air Pod 3nd Gen | 02/13/2026 | Inventory Qty Adjust | 10 |  | \-100.00 | 400.00 | \-40,000.00 | 799.00 | 319,750.00 |
| Air Pod 3nd Gen | 02/13/2026 | Inventory Qty Adjust | 10 |  | \-100.00 | 400.00 | \-40,000.00 | 699.00 | 279,750.00 |
| Air Pod 3nd Gen | 04/14/2026 | Refund | 1026 | JumaTechs | 1.00 | 400.00 | 400.00 | 700.00 | 280,150.00 |
| Air Pod 3nd Gen | 04/14/2026 | Bill |  | Kaniz | 3.00 | 400.00 | 1,200.00 | 703.00 | 281,350.00 |
| Air Pod 3nd Gen | 04/21/2026 | Invoice | 1029 | France | \-40.00 | 400.00 | \-16,000.00 | 663.00 | 265,350.00 |
| Air Pod 3nd Gen | 06/24/2026 | Invoice | 1030 | France | \-90.00 | 400.00 | \-36,000.00 | 573.00 | 229,350.00 |
| Air Pod 3nd Gen | 06/24/2026 | Invoice | 1031 | JumaTechs | \-1.00 | 400.00 | \-400.00 | 572.00 | 228,950.00 |
| **Total for Air Pod 3nd Gen** |  |  |  |  | **572.00** |  | **$228,950.00** |  | **$228,950.00** |
| **Galaxy S25 Ultra 256GB (18)** |  |  |  |  |  |  |  |  |  |
| Galaxy S25 Ultra 256GB | 05/20/2025 | Inventory Starting Value | START |  | 10.00 | 1,000.00 | 10,000.00 | 10.00 | 10,000.00 |
| Galaxy S25 Ultra 256GB | 05/24/2025 | Refund | 1014 | Star Tech | 5.00 | 1,000.00 | 5,000.00 | 15.00 | 15,000.00 |
| Galaxy S25 Ultra 256GB | 05/26/2025 | Bill |  | Binary Burst | 10.00 | 1,200.00 | 12,000.00 | 25.00 | 27,000.00 |
| Galaxy S25 Ultra 256GB | 05/26/2025 | Refund | 1013 | France | 1.00 | 1,200.00 | 1,200.00 | 26.00 | 28,200.00 |
| Galaxy S25 Ultra 256GB | 06/03/2025 | Invoice | 1015 | Suzon Rana | \-10.00 | 1,000.00 | \-10,000.00 | 16.00 | 18,200.00 |
| Galaxy S25 Ultra 256GB | 06/25/2025 | Invoice | 1020 | Zhumur | \-5.00 | 1,000.00 | \-5,000.00 | 11.00 | 13,200.00 |
| Galaxy S25 Ultra 256GB | 06/25/2025 | Invoice | 1020 | Zhumur | \-5.00 | 1,200.00 | \-6,000.00 | 6.00 | 7,200.00 |
| Galaxy S25 Ultra 256GB | 06/25/2025 | Vendor Credit |  | Ragib | \-1.00 | 1,000.00 | \-1,000.00 | 5.00 | 6,200.00 |
| Galaxy S25 Ultra 256GB | 06/25/2025 | Vendor Credit |  | Ragib | 0.00 | \-200.00 | \-200.00 | 5.00 | 6,000.00 |
| Galaxy S25 Ultra 256GB | 07/02/2025 | Sales Receipt | 1021 | France | \-1.00 | 1,200.00 | \-1,200.00 | 4.00 | 4,800.00 |
| Galaxy S25 Ultra 256GB | 07/14/2025 | Invoice | 1023 | France | \-1.00 | 1,200.00 | \-1,200.00 | 3.00 | 3,600.00 |
| Galaxy S25 Ultra 256GB | 09/20/2025 | Invoice | 1024 | JumaTechs:talha bhai | \-1.00 | 1,200.00 | \-1,200.00 | 2.00 | 2,400.00 |
| Galaxy S25 Ultra 256GB | 09/27/2025 | Invoice | 1025 | France | \-1.00 | 1,200.00 | \-1,200.00 | 1.00 | 1,200.00 |
| Galaxy S25 Ultra 256GB | 02/13/2026 | Inventory Qty Adjust | 14 |  | 100.00 | 1,000.00 | 100,000.00 | 101.00 | 101,200.00 |
| Galaxy S25 Ultra 256GB | 04/14/2026 | Invoice | 1027 | France | \-1.00 | 1,000.00 | \-1,000.00 | 100.00 | 100,200.00 |
| Galaxy S25 Ultra 256GB | 04/14/2026 | Credit Memo | 1028 | France | 1.00 | 1,200.00 | 1,200.00 | 101.00 | 101,400.00 |
| Galaxy S25 Ultra 256GB | 06/24/2026 | Invoice | 1031 | JumaTechs | \-1.00 | 1,200.00 | \-1,200.00 | 100.00 | 100,200.00 |
| Galaxy S25 Ultra 256GB | 06/24/2026 | Invoice | 1031 | JumaTechs | \-1.00 | 1,200.00 | \-1,200.00 | 99.00 | 99,000.00 |
| **Total for Galaxy S25 Ultra 256GB** |  |  |  |  | **99.00** |  | **$99,000.00** |  | **$99,000.00** |
| **TOTAL** |  |  |  |  | **671.00** |  | **$327,950.00** |  | **$327,950.00** |

## **11.2  How the key numbers are derived**

**A purchase (stock in).** On 04/23/2025 a Check to JumaTechs brings in 3 Air Pods at 400, so Inventory cost \= 3 × 400 \= \+1,200. Quantity on hand rises from 11 to 14 and Asset value from 4,400 to 5,600.

**A sale (stock out, at FIFO cost).** On 04/20/2025 invoice 1002 sells 1 Air Pod. Under FIFO it is relieved from the opening 400 layer, so Inventory cost \= −1 × 400 \= −400. Quantity on hand falls from 10 to 9 and Asset value from 4,000 to 3,600.

**A value-only vendor credit.** On 06/16/2025 a Binary Burst vendor credit posts Qty 0 with an Inventory cost of \+200 — a pure value adjustment. Quantity on hand stays at 29 while Asset value moves from 12,400 to 12,600.

**A negative-stock moment.** By 06/25/2025 the running Quantity on hand briefly reads −1.00 (Asset value −200.00): stock was relieved before the large 1,000-unit purchase later that day restored it. The report shows this honestly rather than hiding it — a useful red flag.

**Item subtotal and grand total.** Air Pod’s last line leaves 572 units worth 228,950.00, and that is what the “Total for Air Pod 3nd Gen” row reports (net Qty 572, total Inventory cost and ending Asset value both 228,950.00). Galaxy ends at 99 units worth 99,000.00. The grand TOTAL adds them: Qty 671 and Asset value 327,950.00.

| Why the same item leaves at different rates Air Pod sales early in the year are relieved at 400 — the cost of the opening layer. Later, after purchases at 410 and 450, some sales are relieved at 410 and 450 as the cheaper 400 units run out. That is FIFO at work: the Rate on an outbound line is the cost of the oldest stock still on hand, not the price you sold it for. To see selling prices and margin, use a sales or profit-and-loss report instead. |
| :---- |

## **11.3  Reconciling to the Balance Sheet**

The grand total Asset value — here 327,950.00 — is the figure that should match the Inventory asset account on your Balance Sheet as of the same date. If the two disagree, the usual culprits are a transaction posted directly to the inventory account by journal entry (which may not move a specific item), an item whose tracking was turned on after some history already existed, or a date filter that hides part of the activity. Running this report on All Dates and tracing the item that is off is the fastest way to find the difference.

# **12  Common use cases**

The report earns its keep in everyday finance and operations work. A few of the most common ways teams use it:

1. **Verify and reconcile inventory.** Tie the grand total Asset value back to the Inventory asset account on the Balance Sheet at period-end.

2. **Trace an item’s full history.** Follow every purchase, sale, return, and adjustment behind an item’s current quantity and value.

3. **Understand COGS and margins.** See the exact cost relieved on each sale, which is what flows to Cost of Goods Sold under FIFO.

4. **Catch data-entry problems.** Spot negative quantities on hand, purchases booked as plain expenses, or duplicate movements before they distort your books.

5. **Investigate stock discrepancies.** When a physical count doesn’t match the system, the line-by-line trail shows where the difference crept in.

6. **Support audits and period-end close.** Provide a complete, dated valuation trail for each item that an auditor or reviewer can follow.

# **13  Best practices**

* Run the report on All Dates for a true cumulative valuation; narrow the period only when you specifically want one window’s activity.

* Reconcile the grand total Asset value to the Inventory asset account on your Balance Sheet at month-end; investigate any difference.

* Investigate any negative Quantity on hand — it usually means a sale was recorded before its purchase, or a purchase is missing.

* Record inventory purchases against the inventory item (on a Bill, Check, or Expense), not to a plain expense account, so the asset tracks correctly.

* Use Inventory Qty Adjust for shrinkage, damage, and recounts rather than editing or deleting the original transactions.

* Keep item costs accurate when you set up purchases; the Rate drives every value on the line.

* Save a customized version (filtered to one item, or to a single transaction type) so your go-to view is one click away.

# **14  FAQ and troubleshooting**

**Q.  Why does the same item leave inventory at different Rates?**

**A.**  FIFO. Each outbound line is relieved at the cost of the oldest units still on hand, so once a cheaper cost layer runs out, later sales use the next layer’s cost.

**Q.  Why is Quantity on hand negative on some lines?**

**A.**  Stock was sold or removed before the matching purchase was recorded. Enter the missing or mis-dated purchase, and the running balance corrects itself.

**Q.  Why does a line show a value (Inventory cost) but a Qty of 0?**

**A.**  It is a value-only adjustment — typically a vendor credit or cost correction that re-states what the stock is worth without changing the number of units.

**Q.  Why is an Expense or Check on an inventory report?**

**A.**  Those transactions were used to buy stock against the inventory item, so they add units and value just like a Bill.

**Q.  Does this report show my selling price or profit?**

**A.**  No. It is a cost/valuation report — Rate is the cost of the units, not the price you sold them for. Use a sales or profit-and-loss report for revenue and margin.

**Q.  What’s the difference between this and the Inventory Valuation Summary?**

**A.**  The Summary shows one row per item (ending quantity, asset value, and average cost); the Detail (this report) lists every transaction behind those numbers.

**Q.  How is Asset value calculated on each line?**

**A.**  It is a running balance: the previous Asset value plus the current line’s Inventory cost. The final line equals the value of stock still on hand.

**Q.  The total doesn’t match my Balance Sheet — what now?**

**A.**  Run on All Dates, then look for journal entries posted directly to the inventory account, items whose tracking began after some history existed, or a date filter hiding activity.

# **15  Quick reference (cheat sheet)**

| Formulas Inventory cost (line) — Qty × Rate  (value-only adjustments post a cost with Qty 0\) Qty on hand (running) — previous Qty on hand \+ this line’s Qty Asset value (running) — previous Asset value \+ this line’s Inventory cost Item subtotal — net Qty \= ending on hand; total Inventory cost \= ending Asset value Grand total Asset value — \= the Inventory asset on the Balance Sheet |
| :---- |

| Reading a movement Stock in — Bill / Check / Expense, Credit Memo, Refund, positive adjustment — Qty \+, Asset value rises Stock out — Invoice / Sales Receipt, most Vendor Credits, negative adjustment — Qty −, Asset value falls Costing — FIFO — outbound Rate is the oldest layer’s cost, not the sale price Negative on hand — a flag: stock left before it was recorded as received |
| :---- |

Pilucent · Inventory Reporting · Inventory Valuation Detail Report