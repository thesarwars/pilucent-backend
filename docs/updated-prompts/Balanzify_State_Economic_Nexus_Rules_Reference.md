**BALANZIFY**

**State Economic Nexus Rules**

Sales-Tax Threshold Reference for All U.S. Jurisdictions

*Sales thresholds, transaction thresholds, combination logic, includable-sales basis, measurement periods, and registration timing*

This document is the authoritative reference data for Balanzify's Economic Nexus module: the sales-tax registration thresholds and rules for every U.S. state, plus the District of Columbia and Puerto Rico. Each jurisdiction's dollar threshold, transaction threshold, combining logic, which sales count, the measurement window, and when the obligation begins are compiled here in a structured, implementation-ready form so the rule engine can be seeded and maintained directly from it.

| Purpose | Seed and maintenance data for the Economic Nexus rule engine (nexus\_state\_rule) |
| :---- | :---- |
| **Coverage** | 50 states \+ District of Columbia \+ Puerto Rico (45 sales-tax jurisdictions \+ 5 with none) |
| **Data current as of** | July 6, 2026 — reflects confirmed changes through mid-2026, incl. upcoming Kentucky change (Aug 1, 2026\) |
| **Primary sources** | Sales Tax Institute Economic Nexus Chart (5/4/2026); Avalara; Streamlined Sales Tax; state Departments of Revenue |
| **Status** | Compiled reference — verify each state against its Department of Revenue before relying on it for a filing decision |
| **Nature** | Factual compilation. Not legal or tax advice. |

# **Important compliance notice**

| READ THIS BEFORE IMPLEMENTING This is a compiled reference, not legal or tax advice, and it is a snapshot in time. Economic nexus rules are set by each state and change frequently — thresholds are lowered, transaction tests are repealed, and effective dates shift. The data here was compiled from authoritative public sources and cross-checked as of July 6, 2026, but no compiled chart can guarantee every nuance of every state's current law. How to use it safely: treat this document as the seed and maintenance input for the rule engine, and pair it with an ongoing process to confirm each state's current rule against that state's Department of Revenue (and, for material decisions, a qualified sales-tax professional). The module is deliberately built so these rules live as versioned, effective-dated data (not hard-coded), precisely so they can be corrected and updated as law changes. |
| :---- |

## **What this document does and doesn't cover**

* **Covers:** state-level economic (remote-seller) sales-tax nexus thresholds and their mechanics — the dollar threshold, transaction threshold, combining logic, includable-sales basis, measurement period, marketplace treatment, registration timing, and effective/change dates.

* **Does not cover:** physical-presence nexus (inventory, employees, offices — which creates nexus regardless of these thresholds), local/home-rule jurisdiction thresholds (e.g. Alaska localities, Colorado home-rule cities, Louisiana parishes beyond the state framework), product-level taxability, tax rates, or income/franchise tax nexus. Those are handled elsewhere in Balanzify or are out of scope for this reference.

* **Marketplace-facilitator note:** *individual seller's* economic-nexus threshold. This is the least consistent field across sources; where a state is borderline, confirm against its Department of Revenue. Sales a marketplace already collects tax on are generally excluded from what the seller itself must collect.

**Contents**

[**Important compliance notice	2**](#heading=)

[What this document does and doesn't cover	2](#heading=)

[**1   How economic nexus works	4**](#heading=)

[1.1   The building blocks of a state rule	4](#heading=)

[1.2   “Includable sales”: gross vs. retail vs. taxable	4](#heading=)

[1.3   Combination logic: SALES\_ONLY, OR, AND	4](#heading=)

[1.4   Measurement periods	5](#heading=)

[**2   Thresholds at a glance	6**](#heading=)

[2.1   Dollar-threshold tiers	6](#heading=)

[2.2   Transaction-test status	6](#heading=)

[2.3   Includable-sales basis distribution	6](#heading=)

[**3   How to encode these rules	7**](#heading=)

[3.1   Field mapping	7](#heading=)

[3.2   No-sales-tax states	7](#heading=)

[**4   Master table — thresholds & logic	8**](#heading=)

[**5   Measurement period & registration timing	10**](#heading=)

[**6   State-specific notes & nuances	12**](#heading=)

[**7   Recent & upcoming changes	14**](#heading=)

[7.1   Transaction-test removals (state becomes sales-only)	14](#heading=)

[7.2   Dollar-threshold changes	14](#heading=)

[**8   Alaska & the no-sales-tax states	16**](#heading=)

[8.1   The five states with no statewide sales tax	16](#heading=)

[8.2   Alaska is a special case	16](#heading=)

[**9   Seeding & maintenance guidance	17**](#heading=)

[9.1   Loading the data	17](#heading=)

[9.2   Keeping it current	17](#heading=)

[**10   Sources & methodology	18**](#heading=)

[10.1   Methodology & known soft spots	18](#heading=)

# **1   How economic nexus works**

Since the U.S. Supreme Court's 2018 decision in South Dakota v. Wayfair, a state may require an out-of-state (“remote”) seller to register, collect, and remit sales tax once the seller's activity in that state crosses a defined threshold — even with no physical presence there. Every state that levies a sales tax now has such a rule. The thresholds and the way they are measured vary by state, which is exactly what this reference captures.

## **1.1   The building blocks of a state rule**

Each state's rule is made of the same parts. Balanzify encodes every state using these fields:

| Field | What it means | Values used in this reference |
| :---- | :---- | :---- |
| **Sales (dollar) threshold** | The revenue into the state that triggers nexus. | $100,000 (most) · $250,000 (AL, MS) · $500,000 (CA, TX, NY) |
| **Transaction threshold** | A separate count-of-sales trigger, where a state has one. | 200 (most that have one) · 100 (NY) · None (sales-only states) |
| **Combination logic** | How the two thresholds combine. | SALES\_ONLY · OR (either triggers) · AND (both required) |
| **Includable-sales basis** | Which sales count toward the dollar threshold. | Gross · Retail · Taxable (defined in §1.2) |
| **Measurement period** | The window over which activity is measured. | Current/previous calendar year · trailing 12 months · trailing 4 quarters |
| **Marketplace included** | Whether facilitator sales count toward a seller's own threshold. | Yes / No (varies by state) |
| **Registration timing** | When the obligation to collect begins after the threshold is crossed. | Varies — next transaction, first of a later month, following Jan 1, etc. |
| **Effective / change dates** | When the rule (or a change to it) took or takes effect. | Effective-dated per state; see the change log (§7) |

## **1.2   “Includable sales”: gross vs. retail vs. taxable**

States differ on which sales count toward the dollar threshold. This is one of the most consequential distinctions for accurate measurement, so the module tracks it per state.

| Basis | What counts toward the threshold |
| ----- | :---- |
| Gross | All sales into the state — taxable, exempt, and sales for resale. The broadest basis; even a business making only exempt sales can establish nexus. |
| Retail | Retail sales — excludes sales for resale (wholesale), but may still include exempt retail sales. |
| Taxable | Only taxable sales — excludes any non-taxable sales (exempt sales and sales for resale). |

| Because the basis differs, the same sales figure can cross the threshold in one state and not another. The engine sums gross, retail, or taxable per each state's rule — it never assumes all sales count everywhere. |
| :---- |

## **1.3   Combination logic: SALES\_ONLY, OR, AND**

* **SALES\_ONLY —** only the dollar threshold applies; there is no transaction test. The clear majority of states, and the direction every state is trending.

* **OR —** *or* the transaction threshold triggers nexus (whichever is reached first). Common among states that still keep a transaction test (typically $100,000 or 200 transactions).

* **AND — ConnecticutNew York** ($500,000 and 100 transactions). This matters: a high transaction count alone never establishes nexus in an AND state.

| WHY AND LOGIC MUST BE EXACT A seller with 5,000 orders of a $8 item into New York has 5,000 transactions but only $40,000 in sales. Under an OR state that seller would have nexus on the transaction count. New York uses AND, so there is no nexus — both tests must be satisfied. Encoding the logic correctly per state is what prevents false registrations. |
| :---- |

## **1.4   Measurement periods**

Thresholds are measured over a window, and states define the window differently. The module resolves the concrete window from each state's period type:

| Period type | Window | Example states |
| :---- | :---- | :---- |
| **Current or previous calendar year** | Either the current or the prior calendar year triggers. | Most states (e.g. Georgia, Texas uses trailing 12m — see below) |
| **Previous calendar year** | Only the prior full calendar year. | Alabama, Florida, Michigan, New Mexico |
| **Trailing 12 months** | A rolling 12-month window (often reviewed quarterly). | Illinois, Mississippi, Tennessee, Texas, Missouri |
| **Trailing 4 quarters** | The four most recent completed sales-tax quarters. | New York, Vermont |
| **Trailing 12 months ending on a fixed date** | A rolling year ending on a set quarter-end. | Connecticut (ending Sep 30), Minnesota (ending last completed quarter) |

**Implementation note.** The detailed timing table in §6 lists each state's exact measurement language. A handful of states (Connecticut, Minnesota, New York, Vermont, and the trailing-12-month states) use rolling windows rather than plain calendar years; these map to the engine's TRAILING\_12M / TRAILING\_4Q period types and need the rolling-window handling described in the module's technical guide.

# **2   Thresholds at a glance**

Before the full per-state tables, here is the shape of the landscape — the tiers a rule engine must represent.

## **2.1   Dollar-threshold tiers**

| Dollar threshold | Jurisdictions |
| :---- | :---- |
| **$100,000** | The large majority — \~41 jurisdictions (e.g. AZ, CO, GA, IL, NJ, PA, VA, WA, and most others), including DC and Puerto Rico. |
| **$250,000** | Alabama and Mississippi. |
| **$500,000** | California, Texas, and New York (New York also requires 100+ transactions). |

## **2.2   Transaction-test status**

States have been steadily dropping the transaction test. As of July 2026:

| Category | Count | Jurisdictions |
| ----- | :---- | :---- |
| Sales-only (no transaction test) | \~28 | AL, AZ, CA, CO, FL, ID, IL, IN, IA, KS, LA, ME, MA, MS, MO, NM, NC, ND, OK, PA, SC, SD, TN, TX, UT, WA, WI, WY. |
| $ OR transactions (either triggers) | 15 \+ DC \+ PR | AR, GA, HI, KY\*, MD, MI, MN, NE, NV, NJ, OH, RI, VT, VA, WV — plus DC and Puerto Rico. (\*Kentucky drops its transaction test Aug 1, 2026.) |
| AND (both required) | 2 | Connecticut ($100k AND 200); New York ($500k AND 100). |

| A LIVE, MOVING TREND The transaction test is disappearing. Recent removals: Alaska (Jan 1, 2025), Utah (Jul 1, 2025), Illinois (Jan 1, 2026); and Kentucky is scheduled to remove its 200-transaction test on August 1, 2026. Until that date Kentucky remains “$100,000 or 200 transactions.” The change log in §7 lists these so the rule engine can be dated correctly. |
| :---- |

## **2.3   Includable-sales basis distribution**

| Basis | Jurisdictions (per this reference) |
| ----- | :---- |
| Gross | AK, CA, HI, ID, IN, IA, KS, KY, LA (remote), MD, MA, MI, MS, NJ, NC, PA, RI, SC, SD, TX, UT, VT, WA, WV, WI. |
| Retail | AL, CO, CT, DC, GA, IL, MN, NE, NV, OH, TN, VA. |
| Taxable | AR, FL, MO, NM, ND, OK. |

**Note.** Basis classifications follow the Sales Tax Institute chart's convention (gross \= all sales incl. resale, taxable, and exempt; retail \= excludes sales for resale; taxable \= excludes any non-taxable sales). A few states have channel-specific nuances (e.g. Louisiana uses gross for remote sellers and retail for marketplace facilitators; Kansas uses taxable for marketplace facilitators) — these are flagged in the per-state notes (§5.3).

# **3   How to encode these rules**

This reference maps directly onto the module's nexus\_state\_rule table. Each jurisdiction becomes one effective-dated rule row; a change (e.g. Kentucky dropping its transaction test) becomes a new row with a later effective\_from and the prior row's effective\_to closed.

## **3.1   Field mapping**

| Column in this doc | Rule-engine field | Encoding |
| :---- | :---- | :---- |
| Sales threshold | sales\_threshold | Decimal (e.g. 100000). Null only where not applicable. |
| Transaction threshold | txn\_threshold | Integer (e.g. 200\) or NULL for sales-only states. |
| Combination logic | combination\_logic | SALES\_ONLY | OR | AND (NONE for no-sales-tax states). |
| Includable basis | includable\_sales\_basis | GROSS | RETAIL | TAXABLE. |
| Measurement period | measurement\_period\_type | CURRENT\_YEAR | PREVIOUS\_YEAR | CURRENT\_OR\_PREVIOUS\_YEAR | TRAILING\_12M | TRAILING\_4Q. |
| Marketplace included | include\_marketplace\_in\_measurement | Boolean (per-business default can override). |
| Effective / change date | effective\_from / effective\_to | Date-bounded; enables reproducing any past verdict. |
| Registration timing | registration\_timing\_note | Free-text/enum guidance surfaced to the user; does not change the verdict. |

## **3.2   No-sales-tax states**

**Delaware, Montana, New Hampshire, and OregonAlaska***statewide* tax. These are encoded with has\_sales\_tax \= false and combination\_logic \= NONE; the module shows them for completeness but never evaluates them. Alaska is a special case (local-only) covered in §8.

| \-- example encodings (illustrative) \-- California: $500k, sales-only, gross, current-or-previous year ('CA','California', true, 500000, NULL, 'SALES\_ONLY', 'GROSS', 'CURRENT\_OR\_PREVIOUS\_YEAR', DATE '2019-04-01')   \-- New York: $500k AND 100 txns, gross, trailing 4 quarters ('NY','New York', true, 500000, 100, 'AND', 'GROSS', 'TRAILING\_4Q', DATE '2019-06-24')   \-- Connecticut: $100k AND 200 txns, retail, trailing 12m ending Sep 30 ('CT','Connecticut', true, 100000, 200, 'AND', 'RETAIL', 'TRAILING\_12M', DATE '2018-12-01')   \-- Kentucky today: $100k OR 200 txns (until 2026-07-31) ('KY','Kentucky', true, 100000, 200, 'OR', 'GROSS', 'CURRENT\_OR\_PREVIOUS\_YEAR', DATE '2018-10-01', effective\_to \=\> DATE '2026-07-31') \-- Kentucky from Aug 1, 2026: sales-only ('KY','Kentucky', true, 100000, NULL, 'SALES\_ONLY', 'GROSS', 'CURRENT\_OR\_PREVIOUS\_YEAR', DATE '2026-08-01')   \-- No sales tax (e.g. Oregon) ('OR','Oregon', false, NULL, NULL, 'NONE', 'GROSS', 'CURRENT\_OR\_PREVIOUS\_YEAR', DATE '2018-06-21') |
| :---- |

# **4   Master table — thresholds & logic**

The core rule for every jurisdiction. Logic is colour-coded: SALES\_ONLY (green), OR (amber), AND (orange). “Mkt.” shows whether a marketplace facilitator's sales count toward an individual seller's threshold (Incl. / Excl.). Symbols: † Alaska is local-only (no statewide tax); \* Kentucky's transaction test is removed effective Aug 1, 2026 (see §7).

| State | Sales $ | Txn | Logic | Basis | Mkt. |
| :---- | :---- | :---- | ----- | :---- | :---- |
| **Alabama** | $250,000 | None | SALES\_ONLY | Retail | Excl. |
| **Alaska †** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Arizona** | $100,000 | None | SALES\_ONLY | Gross | Excl. |
| **Arkansas** | $100,000 | 200 | OR | Taxable | Excl. |
| **California** | $500,000 | None | SALES\_ONLY | Gross | Incl. |
| **Colorado** | $100,000 | None | SALES\_ONLY | Retail | Excl. |
| **Connecticut** | $100,000 | 200 | AND | Retail | Incl. |
| **Delaware** | — | — | No tax | — | — |
| **District of Columbia** | $100,000 | 200 | OR | Retail | Incl. |
| **Florida** | $100,000 | None | SALES\_ONLY | Taxable | Excl. |
| **Georgia** | $100,000 | 200 | OR | Retail | Excl. |
| **Hawaii** | $100,000 | 200 | OR | Gross | Incl. |
| **Idaho** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Illinois** | $100,000 | None | SALES\_ONLY | Retail | Excl. |
| **Indiana** | $100,000 | None | SALES\_ONLY | Gross | Excl. |
| **Iowa** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Kansas** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Kentucky \*** | $100,000 | 200 | OR | Gross | Incl. |
| **Louisiana** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Maine** | $100,000 | None | SALES\_ONLY | Gross | Excl. |
| **Maryland** | $100,000 | 200 | OR | Gross | Incl. |
| **Massachusetts** | $100,000 | None | SALES\_ONLY | Gross | Excl. |
| **Michigan** | $100,000 | 200 | OR | Gross | Incl. |
| **Minnesota** | $100,000 | 200 | OR | Retail | Incl. |
| **Mississippi** | $250,000 | None | SALES\_ONLY | Gross | Excl. |
| **Missouri** | $100,000 | None | SALES\_ONLY | Taxable | Incl. |
| **Montana** | — | — | No tax | — | — |
| **Nebraska** | $100,000 | 200 | OR | Retail | Incl. |
| **Nevada** | $100,000 | 200 | OR | Retail | Incl. |
| **New Hampshire** | — | — | No tax | — | — |
| **New Jersey** | $100,000 | 200 | OR | Gross | Incl. |
| **New Mexico** | $100,000 | None | SALES\_ONLY | Taxable | Excl. |
| **New York** | $500,000 | 100 | AND | Gross | Incl. |
| **North Carolina** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **North Dakota** | $100,000 | None | SALES\_ONLY | Taxable | Excl. |
| **Ohio** | $100,000 | 200 | OR | Retail | Incl. |
| **Oklahoma** | $100,000 | None | SALES\_ONLY | Taxable | Excl. |
| **Oregon** | — | — | No tax | — | — |
| **Pennsylvania** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Puerto Rico** | $100,000 | 200 | OR | Gross | Excl. |
| **Rhode Island** | $100,000 | 200 | OR | Gross | Incl. |
| **South Carolina** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **South Dakota** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Tennessee** | $100,000 | None | SALES\_ONLY | Retail | Excl. |
| **Texas** | $500,000 | None | SALES\_ONLY | Gross | Incl. |
| **Utah** | $100,000 | None | SALES\_ONLY | Gross | Excl. |
| **Vermont** | $100,000 | 200 | OR | Gross | Incl. |
| **Virginia** | $100,000 | 200 | OR | Retail | Excl. |
| **Washington** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **West Virginia** | $100,000 | 200 | OR | Gross | Incl. |
| **Wisconsin** | $100,000 | None | SALES\_ONLY | Gross | Incl. |
| **Wyoming** | $100,000 | None | SALES\_ONLY | Gross | Excl. |

# **5   Measurement period & registration timing**

For each jurisdiction: the window over which the threshold is measured, when the obligation to collect begins after the threshold is crossed, and the original effective date of the rule. “CY” \= calendar year.

| State | Measurement period | Registration begins | Effective |
| :---- | :---- | :---- | :---- |
| **Alabama** | Previous CY | Jan 1 after year exceeded | Oct 1, 2018 |
| **Alaska †** | Current or previous CY | 1st of month, 30 days after local adoption | 2020 (ARSSTC) |
| **Arizona** | Previous or current CY | 1st of month ≥30 days after threshold | Oct 1, 2019 |
| **Arkansas** | Previous or current CY | Next transaction | Jul 1, 2019 |
| **California** | Preceding or current CY | Day you exceed the threshold | Apr 1, 2019 |
| **Colorado** | Previous or current CY | 1st of month after 90th day sales \> $100k | Dec 1, 2018 |
| **Connecticut** | Trailing 12 months ending Sep 30 | Oct 1 after the Sep 30 crossing | Dec 1, 2018 |
| **District of Columbia** | Previous or current CY | Next transaction | Jan 1, 2019 |
| **Florida** | Previous CY | 1st of the next calendar year | Jul 1, 2021 |
| **Georgia** | Previous or current CY | Next transaction | Jan 1, 2019 |
| **Hawaii** | Current or preceding CY | 1st of month after threshold met | Jul 1, 2018 |
| **Idaho** | Previous or current CY | Next transaction | Jun 1, 2019 |
| **Illinois** | Preceding 12 months (checked quarterly) | Per quarterly determination | Oct 1, 2018 |
| **Indiana** | Current or preceding CY | Next transaction | Oct 1, 2018 |
| **Iowa** | Current or preceding CY | 1st of next month ≥30 days after | Jan 1, 2019 |
| **Kansas** | Current or preceding CY | Next transaction | Jul 1, 2021 |
| **Kentucky \*** | Previous or current CY | 1st of month, 60 days after threshold | Oct 1, 2018 |
| **Louisiana** | Previous or current CY | Register ≤30 days; collect ≤60 days | Jul 1, 2020 |
| **Maine** | Previous or current CY | 1st of month ≥30 days after | Jul 1, 2018 |
| **Maryland** | Previous or current CY | 1st of month after threshold met | Oct 1, 2018 |
| **Massachusetts** | Previous or current CY | 1st of month, 2 months after threshold | Oct 1, 2019 |
| **Michigan** | Previous CY | Jan 1 after year exceeded | Oct 1, 2018 |
| **Minnesota** | Trailing 12 months ending last completed quarter | 1st of month ≤60 days after | Oct 1, 2018 |
| **Mississippi** | Prior 12-month period | Next transaction | Sep 1, 2018 |
| **Missouri** | Previous 12 months (checked quarterly) | ≤3 months after quarter close | Jan 1, 2023 |
| **Nebraska** | Previous or current CY | 1st of 2nd month after threshold | Apr 1, 2019 |
| **Nevada** | Previous or current CY | 1st of month ≥30 days after | Nov 1, 2018 |
| **New Jersey** | Previous or current CY | First taxable sale (30-day grace to register) | Nov 1, 2018 |
| **New Mexico** | Previous CY | Jan 1 after year exceeded | Jul 1, 2019 |
| **New York** | Preceding four sales-tax quarters | Register ≤30 days; collect 20 days later | Jun 21, 2018 |
| **North Carolina** | Previous or current CY | Next transaction | Nov 1, 2018 |
| **North Dakota** | Previous or current CY | Following CY or 60 days, whichever earlier | Oct 1, 2018 |
| **Ohio** | Previous or current CY | Next day after threshold | Aug 1, 2019 |
| **Oklahoma** | Preceding or current CY | 1st calendar month after threshold | Nov 1, 2019 |
| **Pennsylvania** | Prior CY | Apr 1 after year exceeded | Jul 1, 2019 |
| **Puerto Rico** | Seller's fiscal/accounting year | Next transaction | Jan 1, 2021 |
| **Rhode Island** | Immediately preceding CY | Jan 1 after year exceeded | Jul 1, 2019 |
| **South Carolina** | Previous or current CY | 1st of 2nd month after nexus | Nov 1, 2018 |
| **South Dakota** | Previous or current CY | 1st full month ≥30 days after | Nov 1, 2018 |
| **Tennessee** | Previous 12-month period | 1st of 3rd month after threshold | Oct 1, 2019 |
| **Texas** | Preceding 12 calendar months | 1st of 4th month after threshold | Oct 1, 2019 |
| **Utah** | Previous or current CY | Next transaction | Jan 1, 2019 |
| **Vermont** | Prior four calendar quarters | 1st of month, 30 days after quarter end | Jul 1, 2018 |
| **Virginia** | Previous or current CY | Next transaction | Jul 1, 2019 |
| **Washington** | Current or preceding CY | 1st of month ≥30 days after | Oct 1, 2018 |
| **West Virginia** | Preceding or current CY | Next transaction | Jan 1, 2019 |
| **Wisconsin** | Previous or current CY | Next transaction | Oct 1, 2018 |
| **Wyoming** | Previous or current CY | Next transaction | Feb 1, 2019 |

*No-sales-tax states (Delaware, Montana, New Hampshire, Oregon) are omitted from this table; see §8.*

# **6   State-specific notes & nuances**

Where a state has a quirk that affects encoding or measurement, it is called out here. States not listed follow the standard pattern in the tables above.

**Alabama**

Threshold is $250,000 of retail sales; part of Alabama's Simplified Sellers Use Tax (SSUT) program. Marketplace-facilitated sales are excluded from an individual seller's threshold. Measured on the previous calendar year.

**Alaska**

No statewide sales tax — economic nexus is administered locally by the Alaska Remote Seller Sales Tax Commission (ARSSTC) for participating municipalities. $100,000 gross (marketplace included); the 200-transaction test was repealed effective Jan 1, 2025\. See §8 for full treatment.

**Arizona**

Threshold phased down over time: $200,000 (2019), $150,000 (2020), and $100,000 (2021 onward). Now a flat $100,000, sales-only.

**California**

Removed its transaction test and raised the dollar threshold to $500,000 on Apr 25, 2019\. Counts gross sales of tangible personal property; marketplace sales are included toward the seller threshold.

**Colorado**

200-transaction test removed Apr 14, 2019\. Note: Colorado has numerous home-rule cities that administer their own local sales tax and may set separate local thresholds — outside this state-level reference.

**Connecticut**

One of only two AND states: nexus requires $100,000 AND 200 transactions. The dollar threshold was lowered from $250,000 to $100,000 on Jul 1, 2019\. Measured over a trailing 12 months ending September 30\.

**Georgia**

Dollar threshold lowered from $250,000 to $100,000 effective Jan 1, 2020\. $100,000 or 200 transactions; retail sales of TPP (taxable or exempt) count.

**Illinois**

200-transaction test removed effective Jan 1, 2026 (HB 2755\) — now sales-only. Retail sales; measured on a rolling preceding 12 months determined quarterly. Under the Leveling the Playing Field Act, remote retailers collect destination-rate Retailers' Occupation Tax (ROT).

**Indiana**

200-transaction test removed effective Jan 1, 2024 — now $100,000 sales-only (gross).

**Iowa**

200-transaction test removed effective May 3, 2019 — now $100,000 sales-only (gross).

**Kansas**

$100,000, sales-only. Basis is gross for remote sellers, but taxable for marketplace facilitators per Kansas DOR Notice 21-14.

**Kentucky**

Currently $100,000 OR 200 transactions (gross). HB 757 removes the 200-transaction test effective Aug 1, 2026, making it sales-only; the same bill extends sales tax to data-brokering services. Encode as two effective-dated rule versions (see §3.2 and §7).

**Louisiana**

200-transaction test removed effective Aug 1, 2023 — now $100,000 sales-only. Basis is gross for remote sellers and retail for marketplace facilitators. Remote sellers register with the Louisiana Sales and Use Tax Commission for Remote Sellers.

**Maine**

200-transaction test removed effective Jan 1, 2022 — now $100,000 sales-only (gross).

**Massachusetts**

Removed its 100-transaction test and lowered the dollar threshold from $500,000 to $100,000 effective Oct 1, 2019 — now sales-only (gross).

**Minnesota**

$100,000 or 200 transactions (retail). Changed to 200 transactions (from 100\) on Oct 1, 2019\. Measured over a trailing 12 months ending on the last day of the most recently completed calendar quarter.

**Mississippi**

$250,000, sales-only (gross), with a “purposefully or systematically exploiting the market” standard. No transaction test. Measured over the prior 12 months.

**Missouri**

The last state to adopt economic nexus (effective Jan 1, 2023). $100,000 of taxable TPP, marketplace included; measured over the previous 12 months, reviewed quarterly.

**New York**

The other AND state: $500,000 AND more than 100 sales of tangible personal property. Raised from $300,000 to $500,000 on Jun 24, 2019\. Measured over the immediately preceding four sales-tax quarters.

**North Carolina**

Transaction test removed effective Jul 1, 2024 — now $100,000 sales-only (gross).

**North Dakota**

200-transaction test removed effective Dec 31, 2018 (essentially from the start) — $100,000 sales-only; taxable sales basis.

**Ohio**

Lowered from $500,000 to $100,000 or 200 transactions effective Aug 1, 2019\. Retail sales; marketplace included.

**Pennsylvania**

Economic threshold is $100,000 of gross sales across all channels (including taxable, exempt, and marketplace sales). A separate $10,000 notice-and-report option predates the economic-nexus rule.

**South Dakota**

The Wayfair state. Transaction test removed effective Jul 1, 2023 — now $100,000 sales-only (gross).

**Tennessee**

Dollar threshold lowered from $500,000 to $100,000 effective Oct 1, 2020\. Retail sales; marketplace sales excluded for individual sellers from Oct 1, 2020\. Measured over the previous 12 months.

**Texas**

$500,000 “safe harbor” threshold, sales-only. Gross revenue counts — including taxable, nontaxable, and tax-exempt sales. Measured over the preceding 12 calendar months.

**Utah**

200-transaction test removed effective Jul 1, 2025 — now $100,000 sales-only (gross).

**Washington**

200-transaction test removed effective Mar 14, 2019\. Basis changed from retail sales to gross business income effective Jan 1, 2020\. Interacts with Washington's B\&O tax; a separate $10,000 notice option predated the rule.

**Wisconsin**

200-transaction test removed effective Feb 20, 2021 — now $100,000 sales-only (gross). A seller making only marketplace-collected sales need not register.

**Wyoming**

Transaction test removed effective Jul 1, 2024 — now $100,000 sales-only (gross).

# **7   Recent & upcoming changes**

The change log the rule engine must reflect as effective-dated versions. Because these keep coming, treat rule maintenance as an ongoing process, not a one-time seed.

## **7.1   Transaction-test removals (state becomes sales-only)**

| State | Change | Effective |
| :---- | :---- | :---- |
| North Dakota | Removed 200-transaction test | Dec 31, 2018 |
| California | Removed transaction test; raised $ to $500,000 | Apr 25, 2019 |
| Washington | Removed 200-transaction test | Mar 14, 2019 |
| Colorado | Removed 200-transaction test | Apr 14, 2019 |
| Iowa | Removed 200-transaction test | May 3, 2019 |
| Massachusetts | Removed 100-transaction test; $ lowered to $100,000 | Oct 1, 2019 |
| Wisconsin | Removed 200-transaction test | Feb 20, 2021 |
| Maine | Removed 200-transaction test | Jan 1, 2022 |
| Louisiana | Removed 200-transaction test | Aug 1, 2023 |
| South Dakota | Removed transaction test | Jul 1, 2023 |
| Indiana | Removed 200-transaction test | Jan 1, 2024 |
| North Carolina | Removed transaction test | Jul 1, 2024 |
| Wyoming | Removed transaction test | Jul 1, 2024 |
| Alaska (ARSSTC) | Removed 200-transaction test | Jan 1, 2025 |
| Utah | Removed 200-transaction test | Jul 1, 2025 |
| Illinois | Removed 200-transaction test | Jan 1, 2026 |
| **Kentucky** | **Removes 200-transaction test (HB 757\) — upcoming** | **Aug 1, 2026** |

## **7.2   Dollar-threshold changes**

| State | Change | Effective |
| :---- | :---- | :---- |
| New York | Raised from $300,000 to $500,000 (with 100-txn AND test) | Jun 24, 2019 |
| Connecticut | Lowered from $250,000 to $100,000 (with 200-txn AND test) | Jul 1, 2019 |
| Massachusetts | Lowered from $500,000 to $100,000 | Oct 1, 2019 |
| Ohio | Lowered from $500,000 to $100,000 (or 200 txns) | Aug 1, 2019 |
| Georgia | Lowered from $250,000 to $100,000 | Jan 1, 2020 |
| Tennessee | Lowered from $500,000 to $100,000 | Oct 1, 2020 |
| Arizona | Phased to $100,000 ($200k→$150k→$100k) | 2019–2021 |

| WATCH LIST Several other states with a transaction test have signalled interest in removing it (the Streamlined Sales Tax Governing Board encourages member states to do so). New Jersey has considered repeal. Keep the OR-with-transaction states — Arkansas, Georgia, Hawaii, Maryland, Michigan, Minnesota, Nebraska, Nevada, New Jersey, Ohio, Rhode Island, Vermont, Virginia, West Virginia (plus DC and Puerto Rico) — under review, since any of them may drop the transaction test next. |
| :---- |

# **8   Alaska & the no-sales-tax states**

## **8.1   The five states with no statewide sales tax**

**Delaware, Montana, New Hampshire, OregonAlaska**. Encode these with has\_sales\_tax \= false and combination\_logic \= NONE; the module lists them for completeness and never evaluates a verdict for them.

## **8.2   Alaska is a special case**

* **No statewide tax, but local nexus.** Alaska has no state sales tax, yet over 100 local municipalities levy local sales tax. Many collect from remote sellers through a single, coordinated framework: the Alaska Remote Seller Sales Tax Commission (ARSSTC).

* **Threshold.** $100,000 in statewide gross sales (marketplace sales included) in the current or previous calendar year. The 200-transaction test was repealed effective Jan 1, 2025\.

* **Registration.** Sellers register once with the ARSSTC, which covers all participating member jurisdictions; collection begins per the local adoption timing.

* **Implementation choice.** Balanzify may model Alaska as a single “Alaska (ARSSTC)” jurisdiction at the $100,000 gross, sales-only level for measurement, while noting that actual rate calculation and filing occur at the local level through the ARSSTC. Physical presence (e.g. inventory in an Alaska locality) creates local nexus regardless of the threshold.

| HOME-RULE AND LOCAL THRESHOLDS ARE OUT OF SCOPE HERE Beyond Alaska, a few states have local jurisdictions that administer their own sales tax and may set separate thresholds — notably Colorado's home-rule cities and Louisiana's parish framework. This reference covers state-level economic nexus. Local/home-rule thresholds, where they apply, are a separate layer to be handled with local tax data. |
| :---- |

# **9   Seeding & maintenance guidance**

## **9.1   Loading the data**

1. Insert one effective-dated row per jurisdiction into nexus\_state\_rule using the values in §4–§5 and the field mapping in §3.1.

2. Set no-sales-tax states (DE, MT, NH, OR, and Alaska for statewide) with has\_sales\_tax \= false and combination\_logic \= NONE.

3. Encode the Kentucky change as two rows: the current OR rule with effective\_to \= 2026-07-31, and the sales-only rule with effective\_from \= 2026-08-01.

4. Seed idempotently — the unique key (state\_code, effective\_from) lets the seed re-run safely with ON CONFLICT DO NOTHING.

## **9.2   Keeping it current**

* **Apply changes as new versions.** Never edit a rule in place. When a state changes its law, close the current row's effective\_to and insert a new row from the effective date. This preserves the ability to reproduce any past verdict.

* **Review cadence.** Re-verify the full chart at least quarterly, and whenever a change is announced. Transaction-test removals and dollar-threshold changes are the most common events.

* **Confirm against primary sources.** Before relying on any state for a filing decision, confirm its current rule against that state's Department of Revenue. This document is a compiled starting point, not a substitute for the state's own guidance.

* **Monitor the watch list.** The OR-with-transaction states (§7.2) are the likeliest to change next; keep them under closer review.

# **10   Sources & methodology**

This reference was compiled and cross-checked from the following authoritative public sources, current as of July 6, 2026:

* **Sales Tax Institute — Economic Nexus State-by-State Chart** (dated as of 5/4/2026): the primary source for per-state thresholds, measurement dates, includable-sales basis, marketplace treatment, and registration timing.

* **Avalara — state-by-state economic nexus guide** and change bulletins (including the Kentucky HB 757 and transaction-threshold-removal updates): used to cross-check thresholds and confirm 2025–2026 changes.

* **Streamlined Sales Tax (SST) Governing Board** publications: context on transaction-threshold removals across member states.

* **State Departments of Revenue** and enacting legislation (e.g. Illinois HB 2755; Kentucky HB 757): the authoritative primary sources for each state's current rule.

## **10.1   Methodology & known soft spots**

* **Combination logic and period type** were classified into the module's enums (SALES\_ONLY / OR / AND; the measurement-period types) from each state's rule language.

* **The marketplace-inclusion column** is the least consistent field across public sources. Where a state was borderline, the more conservative reading was taken and the state flagged for confirmation against its Department of Revenue.

* **Effective dates** reflect the original economic-nexus effective date; subsequent changes are dated in the change log (§7). A few states phased thresholds (e.g. Arizona) — noted in §6.

| FINAL WORD Use this as the seed, keep it versioned, and verify against each state. The value of this reference is that it turns 52 jurisdictions of shifting rules into structured, dated data your rule engine can consume today — and correct tomorrow. It is a compiled aid, current as of July 6, 2026, and not legal or tax advice; a state's Department of Revenue (and a qualified sales-tax professional for material decisions) is the authority for any specific filing question. |
| :---- |

