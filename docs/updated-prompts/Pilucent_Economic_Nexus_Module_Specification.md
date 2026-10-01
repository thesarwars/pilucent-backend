**PILUCENT**

**Economic Nexus**

Module Specification & Technical Design

*Sales-tax obligation tracking for the Sales Tax suite*

This document is the end-to-end blueprint for the Economic Nexus module — the part of Pilucent that watches a business's sales in every U.S. state, compares them against each state's sales-tax registration thresholds, and tells the owner exactly where and when they have become obligated to collect and remit sales tax. It is written so that a product manager, an engineer, and an accountant can all read the same pages and share one mental model of the feature.

| Document | Economic Nexus — Module Specification (PRD \+ Technical Design) |
| :---- | :---- |
| **Product area** | Sales Tax suite  ·  builds on Sales, Expenses, Customers, Products & Services |
| **Version** | 1.0  —  Draft for engineering review |
| **Status** | Ready for grooming |
| **Primary audience** | Engineering, Product, QA, and the Accounting/Compliance reviewer |
| **Reference-data currency** | State thresholds compiled from public sources as of Oct 2025, with confirmed 2025–2026 changes folded in (see §9) |

# **Document control**

## **Revision history**

| Version | Date | Author | Summary of change |
| :---- | :---- | :---- | :---- |
| 0.1 | Initial draft | Product | Skeleton, goals, scope, glossary. |
| 0.5 | Working draft | Product \+ Eng | Feature specs, data model, calculation logic added. |
| 1.0 | This revision | Product \+ Eng \+ Accounting | Accounting treatment, reports, state reference data, and acceptance criteria completed. Circulated for grooming. |

## **How to read this document**

The document moves from the general to the specific. If you only have five minutes, read the executive summary (§1) and the feature list (§8). If you are about to build, the sections you will live in are the data model (§11), the calculation logic (§12), the module integrations (§13), and the accounting treatment (§14).

* **Sections 2–7** set the context: what economic nexus is, who the module is for, and the language we use for it.

* **Section 8** is the heart of the spec — every feature, one at a time, each with a goal, a user story, the underlying logic, the on-screen behaviour, the data it reads, its edge cases, and its acceptance criteria.

* **Sections 9–16** are the engineering detail: reference data, flows, schema, algorithms, integrations, accounting posting, and reports.

* **Sections 17–21** close the loop with business rules, non-functional requirements, risks, a delivery plan, and appendices.

| A NOTE ON WORDING Throughout, "the business" means the company whose books are open in Pilucent, and "the user" means whoever is looking at the screen — usually the owner, a bookkeeper, or their accountant. "State" is shorthand for any U.S. sales-tax jurisdiction we track, which includes the District of Columbia. |
| :---- |

**Table of contents**

[**Document control	2**](#heading=)

[Revision history	2](#heading=)

[How to read this document	2](#heading=)

[**1   Executive summary	4**](#heading=)

[**2   Understanding economic nexus	5**](#heading=)

[2.1   What "nexus" means	5](#heading=)

[2.2   Physical nexus vs. economic nexus	5](#heading=)

[2.3   How a threshold is measured	5](#heading=)

[2.4   Measurement periods and trailing nexus	6](#heading=)

[2.5   Remote sellers and marketplace facilitators	6](#heading=)

[2.6   Why this matters to our users	6](#heading=)

[**3   Module goals & success metrics	8**](#heading=)

[3.1   Goals	8](#heading=)

[3.2   Success metrics	8](#heading=)

[**4   Scope	9**](#heading=)

[4.1   In scope (release 1\)	9](#heading=)

[4.2   Out of scope (release 1\)	9](#heading=)

[4.3   Future phases	9](#heading=)

[**5   Personas	10**](#heading=)

[**6   Glossary	11**](#heading=)

[**7   User stories	12**](#heading=)

[**8   Feature specification	13**](#heading=)

[F1   Nexus dashboard	13](#heading=)

[F2   State column & registration indicator	14](#heading=)

[F3   Date range (measurement window)	15](#heading=)

[F4   Sales column	15](#heading=)

[F5   Transaction count column	16](#heading=)

[F6   Threshold met column	17](#heading=)

[F7   Agency setup	18](#heading=)

[F8   Last updated	18](#heading=)

[F9   Inline help & education	19](#heading=)

[F10   Approaching & met alerts	19](#heading=)

[F11   State detail view	20](#heading=)

[F12   Recalculation engine	21](#heading=)

[**9   State-by-state threshold reference data	22**](#heading=)

[**10   End-to-end user flows	25**](#heading=)

[10.1   First look — reviewing exposure	25](#heading=)

[10.2   A sale nudges a state toward its threshold	25](#heading=)

[10.3   A threshold is crossed	25](#heading=)

[10.4   Registering and turning on collection	25](#heading=)

[10.5   Manually marking physical nexus	26](#heading=)

[10.6   Advising a client (accountant)	26](#heading=)

[**11   Data model & schema	27**](#heading=)

[11.1   Entities at a glance	27](#heading=)

[11.2   Entity detail	27](#heading=)

[11.3   Relationships	29](#heading=)

[**12   Calculation logic & algorithms	30**](#heading=)

[12.1   Resolving the measurement window	30](#heading=)

[12.2   Aggregating sales and counting transactions	30](#heading=)

[12.3   Evaluating the threshold verdict	31](#heading=)

[12.4   Deriving the display status	31](#heading=)

[12.5   Detecting crossings and raising alerts	31](#heading=)

[12.6   When recalculation runs	32](#heading=)

[**13   Integration with other modules	33**](#heading=)

[13.1   The Sales Tax handoff in detail	33](#heading=)

[**14   Accounting treatment	34**](#heading=)

[14.1   Accounts involved	34](#heading=)

[14.2   Recording a taxable sale (after registration)	34](#heading=)

[14.3   Customer payment	34](#heading=)

[14.4   Refund or return of a taxable sale	35](#heading=)

[14.5   Remitting tax to the state	35](#heading=)

[14.6   Exposure before registration (advanced, future)	35](#heading=)

[14.7   Ledger view and reconciliation	36](#heading=)

[**15   Reporting	37**](#heading=)

[15.1   Economic Nexus Exposure report	37](#heading=)

[15.2   Approaching-Risk report	37](#heading=)

[15.3   Threshold-History (audit trail)	37](#heading=)

[15.4   Relationship to the Sales Tax Liability report	37](#heading=)

[**16   Notifications & automation rules	38**](#heading=)

[**17   Business rules & edge cases	39**](#heading=)

[**18   Non-functional requirements	40**](#heading=)

[18.1   Performance & scale	40](#heading=)

[18.2   Data currency & maintenance	40](#heading=)

[18.3   Auditability	40](#heading=)

[18.4   Security & tenancy	40](#heading=)

[18.5   Accessibility	40](#heading=)

[18.6   Localisation & coverage	40](#heading=)

[**19   Assumptions, dependencies & risks	41**](#heading=)

[19.1   Assumptions	41](#heading=)

[19.2   Dependencies	41](#heading=)

[19.3   Risks & mitigations	41](#heading=)

[**20   Phased delivery plan	42**](#heading=)

[**21   Appendix	43**](#heading=)

[21.1   Illustrative API surface	43](#heading=)

[21.2   Example rule-change log (why versioning matters)	43](#heading=)

[21.3   Source landscape	43](#heading=)

# **1   Executive summary**

Every business that sells across state lines faces a quiet, creeping risk: it can become legally obligated to collect sales tax in a new state without doing anything except growing. The trigger is not opening an office or hiring staff — it is simply crossing a sales or transaction threshold that each state sets for out-of-state sellers. Cross it unknowingly and the business is on the hook for tax it never collected, plus penalties and interest. This is the problem the Economic Nexus module exists to solve.

The module continuously reads the sales the business has already recorded in Pilucent, groups them by the state the customer is in, and measures that activity against each state's published thresholds. It presents the result as a single, scannable dashboard: one row per state, showing how much the business has sold there, how many transactions that represents, and — the answer everyone actually wants — whether the state's threshold has been *met*. When a threshold is crossed, the module flags it, points the user toward registering with that state's tax agency, and hands off cleanly to the Sales Tax module so that tax starts being calculated on new invoices.

Crucially, nexus tracking is a monitoring and compliance layer, not a bookkeeping event in itself. Watching sales cross a line does not create a journal entry. What it does is tell the business when to switch tax collection on for a state; the journal entries follow from that collection and its later remittance. Section 14 documents that accounting lifecycle in full so there is no ambiguity about what posts, when, and to which accounts.

| WHAT SUCCESS LOOKS LIKE No surprises. A business owner learns they are approaching a state's threshold before they cross it — not from a state audit letter two years later. One glance. The dashboard answers "where do I owe sales tax?" without the user memorising 46 different state rules. A clean handoff. Registering for a state flows straight into agency setup and tax calculation, with the books staying consistent throughout. |
| :---- |

# **2   Understanding economic nexus**

This section is the shared domain background. Engineers do not need to become tax experts, but the logic in this module only makes sense once these ideas are clear. Read it once and the rest of the spec falls into place.

## **2.1   What "nexus" means**

Nexus is the legal connection between a business and a state that gives the state the right to require the business to collect and remit its sales tax. No nexus, no obligation. For decades, that connection meant physical presence — a store, a warehouse, an employee, inventory sitting in the state. If a seller had none of those, it did not have to collect that state's sales tax, no matter how much it sold there.

That changed in June 2018 with the U.S. Supreme Court decision in *South Dakota v. Wayfair, Inc.* The Court held that a state may require an out-of-state seller to collect sales tax based purely on the seller's **economic activity** in the state — its sales revenue and/or number of transactions — even with zero physical presence. This new basis is called **economic nexus**. Within about two years, every U.S. state that levies a sales tax had enacted an economic-nexus law.

## **2.2   Physical nexus vs. economic nexus**

Both kinds of nexus create the same obligation to collect tax; they simply arise for different reasons. The module focuses on economic nexus because that is the one driven by data Pilucent already holds. Physical nexus is a fact the user must tell us about, because we cannot infer an office or a remote employee from sales records.

|  | Physical nexus | Economic nexus |
| :---- | :---- | :---- |
| Triggered by | A physical footprint: office, store, warehouse, inventory, employees, or contractors in the state. | Crossing the state's sales-dollar and/or transaction-count threshold for remote sellers. |
| How we know | The user declares it (Pilucent cannot detect it from data). | Pilucent calculates it automatically from recorded sales. |
| This module's role | Lets the user mark a state as having nexus manually, so it is treated as registered. | The core job — measure activity and detect when a threshold is met. |

## **2.3   How a threshold is measured**

A state's threshold has up to two parts, and states combine them differently. Getting this combination right is the single most important piece of logic in the module.

* **Sales-dollar threshold.** A revenue figure — most commonly $100,000, but $250,000 in a few states and $500,000 in California, Texas, and New York. Once cumulative qualifying sales into the state reach this figure, the sales test is met.

* **Transaction-count threshold.** A count of separate sales — usually 200 (100 in New York). Many states have this too, though the clear trend is states dropping it and keeping only the dollar test.

Two states combine the tests with AND; the rest use OR:

| Combination logic | Meaning | States |
| :---- | :---- | :---- |
| **OR**  (default) | Nexus exists once EITHER the sales dollars OR the transaction count is reached. | Most states with two tests (e.g. Georgia, Ohio, Michigan, Minnesota). |
| **AND** | Nexus exists only when BOTH the sales dollars AND the transaction count are reached. | Connecticut ($100k AND 200), New York ($500k AND 100). |
| **Sales only** | There is no transaction test at all; only the dollar figure matters. | A growing majority — e.g. California, Texas, Florida, Pennsylvania. |

| WHY AND VS OR IS NOT A DETAIL A stationery seller with 5,000 orders of $8 stickers into New York has 5,000 transactions but only $40,000 in sales. Under an OR state that seller would already have nexus on the transaction count. New York uses AND, so the seller has no nexus there — both tests must be satisfied. Applying the wrong combination tells a business to register when it should not, or worse, stays silent when it should have warned. The rule engine (§12) must honour each state's combination exactly. |
| :---- |

There is one more subtlety: what counts toward the dollar figure. States differ on whether the threshold measures gross sales (everything, including exempt and resale sales), retail sales (excluding sales for resale), or only taxable sales. The module stores this "includable sales basis" per state so the aggregation sums the right number rather than assuming all sales count.

## **2.4   Measurement periods and trailing nexus**

Thresholds are not measured over all of history — they are measured over a window, and states define the window differently. The three common shapes are the current calendar year, the previous calendar year, and a rolling (trailing) twelve months. Most states say: if you crossed the threshold in the current or the prior calendar year, you have nexus now. The module stores each state's measurement-period type and sums sales over the matching window rather than over the whole ledger.

"Trailing nexus" is the tail end of the obligation. Once a business has nexus, it usually cannot stop collecting the instant its sales dip below the threshold — many states keep the obligation alive through the end of the current year, or for a fixed period afterward. The module records this so it does not prematurely tell a business it is off the hook. In this first release we surface the concept and let the user keep a state active; automated trailing-nexus expiry is noted as a future enhancement in *§4.3*.

## **2.5   Remote sellers and marketplace facilitators**

Two terms shape which sales count. A remote seller is a business selling into a state where it has no physical presence — the classic economic-nexus case. A marketplace facilitator is a platform (think large online marketplaces) that lists other sellers' products and, under most states' laws, collects and remits the sales tax on those sales itself.

This matters because marketplace sales are often already taxed by the facilitator, yet many states still count those sales toward the seller's own threshold. The module therefore lets a sale be tagged with its channel so that, per state rules, facilitator sales can be included in the threshold measurement while being excluded from what the business itself must collect. The default in release 1 is to include all recorded sales in the measurement and let the user exclude a channel where a state's rules allow it.

## **2.6   Why this matters to our users**

For the people using Pilucent, economic nexus is equal parts confusing and consequential. The rules vary by state, they change from year to year, and the penalty for missing a threshold is real money. A small seller who quietly crossed a state's line three years ago can face a demand for years of back tax, plus penalties and interest, on sales for which they never collected a cent. The module's whole reason for existing is to turn that invisible, ever-moving risk into a plain-language status the user can act on in time.

# **3   Module goals & success metrics**

## **3.1   Goals**

* **Give a complete, always-current picture** of the business's sales-tax exposure in every U.S. state on one screen.

* **Detect threshold crossings automatically** from sales the business already records, with no manual data entry.

* **Warn early** as the business approaches a threshold, not only after it has been crossed.

* **Make the next step obvious** — register with the state and turn on tax collection — and connect that step to the rest of the product.

* **Keep the books correct** by clearly separating nexus monitoring (no accounting impact) from tax collection and remittance (which post to a liability account).

* **Stay trustworthy over time** by treating the state-rule set as maintained reference data that is versioned and updated as laws change.

## **3.2   Success metrics**

| Metric | What it tells us | Target signal |
| :---- | :---- | :---- |
| Threshold-crossing lead time | How far ahead of crossing a user is warned. | Users receive an "approaching" alert before the crossing in the large majority of cases. |
| Time-to-register after a crossing | Whether the handoff to agency setup works. | Materially shorter than manual tracking; most crossings acted on within the filing window. |
| Dashboard accuracy | Do our numbers match the state's own view. | Aggregated sales and counts reconcile to the Sales Tax Liability report for the same period. |
| Adoption | Are multi-state sellers turning it on. | Steady uptake among businesses invoicing customers in more than one state. |
| Rule-set freshness | Are we current with the law. | Every confirmed statutory change reflected in the rule engine before its effective date. |

# **4   Scope**

## **4.1   In scope (release 1\)**

* A Nexus dashboard listing all U.S. sales-tax states (plus the District of Columbia), each with its measurement window, sales, transaction count, threshold-met status, agency-setup state, and last-updated time.

* A maintained state-rule engine holding each state's sales threshold, transaction threshold, combination logic, includable-sales basis, and measurement-period type.

* An aggregation engine that sums qualifying sales and counts transactions by ship-to state over each state's window, sourced from recorded sales.

* Threshold evaluation producing a clear status: not approaching, approaching, met (unregistered), or registered.

* Approaching-threshold and threshold-met alerts surfaced in-product and via the notification centre.

* A per-state detail view explaining how the status was reached and what to do next.

* Agency-setup handoff that connects a met/at-risk state to the Sales Tax module's agency registration and turns on tax calculation for that state.

* A manual override to mark a state as having nexus (e.g. physical presence) even if thresholds are not met.

* Nexus reports: an exposure report, an approaching-risk report, and a threshold-history audit trail.

## **4.2   Out of scope (release 1\)**

* Filing or remitting returns to state agencies on the user's behalf. The module tells the user where they owe and hands off to tax collection; it does not submit returns.

* Automated state registration. We guide and link out; we do not file the registration.

* Pulling sales from external channels that are not already synced into Pilucent. The measurement is only as complete as the sales recorded in the product.

* Income-tax nexus, franchise-tax nexus, and non-U.S. (VAT/GST) obligations. This module is U.S. sales-and-use tax only.

* Storing or validating customer exemption certificates (tracked as a related but separate capability).

## **4.3   Future phases**

* **Automated trailing-nexus expiry** — calculate when an obligation lapses after sales fall away, per each state's rule.

* **Marketplace-channel automation** — per-state inclusion/exclusion of facilitator sales applied automatically from channel tags.

* **Registration assistance** — pre-filled registration guidance and, where possible, direct links into state portals.

* **Return preparation** — generate return-ready figures per agency, extending the Sales Tax Liability report.

* **Exposure quantification** — estimate uncollected back-tax where a threshold was crossed before collection began (see §14.6).

# **5   Personas**

Three people touch this module. Designing for all three keeps it both simple enough for an owner and precise enough for an accountant.

| Persona | Who they are | What they need from this module |
| :---- | :---- | :---- |
| **Priya** — Owner / founder | Runs a growing online business. Not an accountant; understands her numbers but not 46 state tax codes. | A plain-language answer to "am I about to owe tax somewhere new?" and a nudge before it becomes a problem. |
| **Marcus** — Bookkeeper | Keeps the books day to day, in Pilucent constantly. | Reliable alerts, a clear per-state status, and a clean path to turn on collection once a state is triggered. |
| **Elena** — Accountant / CPA | Advises several client businesses via the accountant tools; owns compliance risk. | An accurate exposure view per client, an audit trail of when thresholds were crossed, and confidence the books reflect it. |

| *Design implication:* the default surface is scannable and non-technical for Priya; the detail view and reports carry the depth Marcus and Elena need. Nothing forces an owner to understand measurement periods to get value, but the information is one click away for those who do. |
| :---- |

# **6   Glossary**

A shared vocabulary. These terms recur throughout the spec and appear verbatim in the UI, the data model, and the code.

| Term | Definition |
| :---- | :---- |
| **Nexus** | The legal connection that obligates a business to collect and remit a state's sales tax. |
| **Physical nexus** | Nexus arising from a physical footprint (office, inventory, employees) in a state. |
| **Economic nexus** | Nexus arising purely from sales activity crossing a state's threshold, without physical presence. |
| **Sales threshold** | The dollar amount of qualifying sales into a state that triggers nexus (e.g. $100,000). |
| **Transaction threshold** | The count of separate sales into a state that triggers nexus (e.g. 200), where the state has one. |
| **Combination logic** | How a state combines its two tests: OR, AND, or sales-only. |
| **Includable sales basis** | Which sales count toward the dollar threshold: gross, retail, or taxable sales. |
| **Measurement period** | The window over which activity is measured: current year, prior year, or trailing 12 months. |
| **Threshold met** | The condition where a state's rule is satisfied and the business has economic nexus there. |
| **Approaching** | A pre-crossing state where activity has reached a warning fraction (e.g. 80%) of a threshold. |
| **Trailing nexus** | The continued obligation to collect for a period after sales fall below the threshold. |
| **Remote seller** | A business selling into a state where it has no physical presence. |
| **Marketplace facilitator** | A platform that lists third-party sellers and collects/remits tax on their sales. |
| **Tax agency** | The state (or local) authority a business registers with to collect and remit sales tax. |
| **Registration** | Signing up with a tax agency for a permit, after which the business must collect tax. |
| **Sales Tax Payable** | The balance-sheet liability account holding tax collected from customers until remitted. |
| **Ship-to state** | The destination state of a sale — generally what determines which state's rule applies. |

# **7   User stories**

The work grouped into epics, each expressed as the outcomes a user wants. These stories drive the features in §8 and the acceptance criteria attached to them.

### **Epic A — See exposure across all states**

* **As an owner,** I want one screen listing every state with my sales, transactions, and whether I've met the threshold *so that I know at a glance where I might owe sales tax.*

* **As a bookkeeper,** I want the states where we're already registered pinned and clearly marked *so that I can separate settled states from ones still to watch.*

### **Epic B — Understand a single state**

* **As an owner,** I want to open a state and see how its number was calculated and what its rule is *so that I trust the status and understand why.*

* **As an accountant,** I want to see the exact measurement window and includable-sales basis a state uses *so that I can advise the client precisely.*

### **Epic C — Be warned in time**

* **As an owner,** I want an alert when I'm approaching a state's threshold *so that I can prepare before I'm obligated.*

* **As a bookkeeper,** I want a notification the moment a threshold is actually crossed *so that we act within the state's filing window.*

### **Epic D — Register and turn on collection**

* **As a bookkeeper,** I want to go from a met state straight into setting up its tax agency *so that collection starts without re-keying anything.*

* **As an owner,** I want tax to start calculating on new invoices to that state automatically after I register *so that I stop under-collecting.*

### **Epic E — Keep the books right**

* **As an accountant,** I want confidence that nexus tracking alone doesn't touch the ledger *so that monitoring never distorts the financials.*

* **As a bookkeeper,** I want collected tax to post to a clear liability account and reduce when I remit *so that the balance sheet always shows what we owe the state.*

### **Epic F — Report for compliance**

* **As an accountant,** I want an exposure report and a history of when each threshold was crossed *so that I have an audit trail if a state ever asks.*

* **As an owner,** I want a list of states I'm getting close to *so that I can plan ahead.*

# **8   Feature specification**

This section walks the module feature by feature. The features map directly onto the columns and behaviours of the Nexus dashboard, followed by the supporting engine and intelligence features. Each feature carries the same anatomy: its goal, the user story it serves, the logic underneath, how it behaves on screen, the data it reads, its edge cases, and the acceptance criteria QA will test against.

| Ref | Feature | In short |
| :---- | :---- | :---- |
| F1 | Nexus dashboard | The all-states overview table and its controls. |
| F2 | State & registration indicator | State names, and the marker/pinning for registered states. |
| F3 | Date range (measurement window) | The per-state window activity is measured over. |
| F4 | Sales column | Qualifying sales into the state over the window. |
| F5 | Transaction count column | Count of qualifying sales into the state. |
| F6 | Threshold met column | The yes/no/approaching verdict and its logic. |
| F7 | Agency setup | Register the state and turn on tax collection. |
| F8 | Last updated | When the row was last recalculated. |
| F9 | Inline help & education | Column tooltips and the learn-more content. |
| F10 | Approaching & met alerts | Proactive warnings before and at a crossing. |
| F11 | State detail view | The per-state drill-down explaining the status. |
| F12 | Recalculation engine | How and when the numbers refresh. |

## **F1   Nexus dashboard**

**Goal**

Give the user a single, scannable table that answers "where do I have — or am I approaching — a sales-tax obligation?" across all U.S. states, without them needing to know any state's rules by heart.

**Primary user story**

As an owner, I want one screen that lists every state with my sales, transaction count, and whether I've met the threshold, so that I can see my whole sales-tax exposure at a glance.

**Functional logic**

* The dashboard renders one row per tracked state. Tracked states are all U.S. states that levy a sales tax, plus the District of Columbia.

* States without a statewide sales tax are shown for completeness but marked as not applicable and never evaluated for a threshold (see §9).

* Rows are sorted so that states the business is already registered in (or has manually marked) rise to the top; the remaining states follow alphabetically. This mirrors the intent of a business wanting settled states first.

* Each row is populated from the calculation engine (§12): the measurement window, the summed sales, the transaction count, the threshold-met verdict, the agency-setup state, and the last-recalculated timestamp.

* A short educational header explains economic nexus in one sentence and links to the learn-more content (F9).

**On-screen behaviour**

* Columns, left to right: State, Date range, Sales, Transaction count, Threshold met, Agency setup, Last updated.

* Registered states are visually distinguished (bold state name with a filled check), so the eye separates them instantly from states still being watched.

* Each column header carries a help affordance (the "?" tooltip) explaining what the column measures — wired to F9.

* Selecting any row opens that state's detail view (F11).

* An empty state (a business selling into only its home state, or a brand-new company) shows an explanatory message rather than a wall of zeroes.

**Data & sources**

* nexus\_state\_status supplies the per-state row values; nexus\_state\_rule supplies the window and thresholds; nexus\_agency\_registration supplies registration state for sorting and the check marker.

**Edge cases**

* A state with zero sales still appears, showing $0 / 0 transactions / not met — never hidden.

* A newly added state rule (e.g. a jurisdiction we begin tracking) appears automatically once present in the rule set.

* If the engine has never run for a business, rows show a "calculating" placeholder until the first run completes.

**Acceptance criteria**

1. All sales-tax states plus D.C. are listed, one row each, with the seven columns in the defined order.

2. Registered/manually-marked states sort above the rest; the rest are alphabetical.

3. Registered states are visually marked distinctly from unregistered states.

4. Selecting a row opens the corresponding state detail view.

5. A business with no qualifying multi-state sales sees a helpful empty state, not an error.

## **F2   State column & registration indicator**

**Goal**

Identify each jurisdiction unambiguously and show, at a glance, which states are already handled (registered or manually marked) versus still under watch.

**Primary user story**

As a bookkeeper, I want the states we're already registered in pinned and clearly marked, so that I can separate settled states from ones still to watch.

**Functional logic**

* A state's marker reflects its registration status from nexus\_agency\_registration: a filled check when registered or manually marked as having nexus; no marker otherwise.

* Manual marking (F7) and real registration both count as "handled" for the marker and the sort.

* The state name is the stable key; the module keys all internal data on the two-letter state code, never the display name.

**On-screen behaviour**

* Registered/marked states render the name in bold with the check; unregistered states render in normal weight.

* Hovering the marker reveals whether the state is registered, manually marked, or approaching.

**Edge cases**

* A state can be manually marked as having nexus without meeting a threshold (physical presence) — it still gets the check and pins to the top.

* Un-marking or de-registering a state returns it to the watched group and removes the check.

**Acceptance criteria**

1. Registered and manually-marked states show the check and sort to the top.

2. Unregistered states show no check and sort alphabetically below.

3. All lookups resolve on state code, so display-name changes never break data.

## **F3   Date range (measurement window)**

**Goal**

Show the exact window each state's activity is measured over, because "how much have I sold there" is meaningless without the period it covers — and states define that period differently.

**Primary user story**

As an accountant, I want to see the exact measurement window a state uses, so that I can advise the client precisely.

**Functional logic**

* Each state's window derives from its measurement\_period\_type: current calendar year, previous calendar year, or a rolling trailing twelve months.

* The engine resolves the type into concrete start and end dates relative to today and uses exactly that span when summing sales and counting transactions (F4, F5).

* Where a state's law considers both the current and prior year, the module measures the span that captures the crossing and shows the effective window.

**On-screen behaviour**

* The column shows the resolved date span (start – end) for the state, not an abstract label.

* The tooltip explains the window type in words (e.g. "rolling 12 months ending today").

**Edge cases**

* At a year boundary, current-year windows reset; the module recalculates windows as the calendar advances.

* A business onboarded mid-year has a window that legitimately starts before it began using Pilucent; the module measures only the sales it actually holds and notes that history may be incomplete.

**Acceptance criteria**

1. Each row shows a concrete date span matching the state's period type.

2. Windows recompute correctly across a calendar-year boundary.

3. The tooltip states the window type in plain language.

## **F4   Sales column**

**Goal**

Show the qualifying sales the business has made into the state over its window — the figure compared against the dollar threshold.

**Primary user story**

As an owner, I want to see how much I've sold into each state, so that I understand how close I am to owing tax there.

**Functional logic**

* The engine sums sales into the state per its includable\_sales\_basis: gross (all sales), retail (excluding sales for resale), or taxable (excluding exempt sales).

* A sale's state is its ship-to state, taken from the customer's shipping address on the transaction; where no ship-to exists (e.g. a service), the billing state is used, with the rule documented in §12.

* Credits, refunds, and returns reduce the summed figure so the number reflects net qualifying sales.

* Only sales within the resolved window (F3) are counted.

**On-screen behaviour**

* Displayed as a currency figure in the business's home currency.

* The cell subtly conveys proximity to the threshold (e.g. emphasis as the figure nears the limit); the precise percentage lives in the detail view (F11).

**Data & sources**

* Source: recorded sales (invoices and sales receipts) from the Sales module, joined to the customer's ship-to state and the product's taxability. See §13.

**Edge cases**

* A sale spanning multiple ship-to destinations is attributed per line to each destination state.

* A voided transaction is excluded entirely; a partially refunded one is netted.

* Multi-currency sales are converted to the home currency using the transaction's recorded rate before summing.

**Acceptance criteria**

1. The sales figure equals the sum of qualifying sales into the state over the window, per the state's includable basis.

2. Refunds and returns reduce the figure; voids are excluded.

3. Ship-to state (or the documented fallback) determines attribution.

4. The figure reconciles to the Sales Tax Liability report for the same state and period.

## **F5   Transaction count column**

**Goal**

Show the number of qualifying sales into the state over its window — the figure compared against a transaction threshold, where the state has one.

**Functional logic**

* The engine counts distinct qualifying sales into the state within the window. A single invoice is generally one transaction, regardless of the number of line items — but the counting rule follows the state's definition and is centralised in §12.

* Fully refunded or voided transactions do not count; the treatment of partial refunds is defined in §12 and applied consistently.

* For sales-only states (no transaction test), the count is still shown for transparency but never affects the verdict.

**On-screen behaviour**

* Displayed as an integer. Where the state has no transaction test, a subtle indicator notes the count is informational.

**Edge cases**

* Very high transaction counts on tiny order values are exactly the case AND-logic states guard against — the count alone must not drive the verdict in those states.

**Acceptance criteria**

1. The count equals the number of qualifying transactions into the state over the window.

2. Voids and full refunds are excluded; partial refunds follow the documented rule.

3. In sales-only states the count never changes the threshold verdict.

## **F6   Threshold met column**

**Goal**

Deliver the answer the whole dashboard exists for: has this state's threshold been met? And do it using each state's exact combination logic.

**Primary user story**

As an owner, I want a clear yes/no on whether I've crossed each state's threshold, so that I know where I must start collecting tax.

**Functional logic**

* **Sales test:** qualifying sales (F4) ≥ the state's sales threshold.

* **Transaction test:** transaction count (F5) ≥ the state's transaction threshold, only where one exists.

* **Combination:** if the state is AND, both tests must pass; if OR, either passes; if sales-only, only the sales test applies. This is driven entirely by the state's stored logic — never hard-coded per state in the UI.

* **Approaching:** if not met but qualifying sales have reached the warning fraction (default 80%) of the sales threshold — or the transaction count has reached the warning fraction of the transaction threshold in a state where that could trigger — the state is flagged as approaching rather than a plain "no".

* The first moment a state flips to met, the engine stamps threshold\_met\_date and raises the crossing alert (F10). That date is immutable history.

**On-screen behaviour**

* Three visual states: not met (neutral), approaching (amber/caution), met (positive/attention) — colour paired with text and an icon, never colour alone, for accessibility.

* A met state shows a subtle call to action toward agency setup (F7).

* The tooltip explains which test(s) drove the verdict.

**Edge cases**

* A state that was met, then had sales fall below the threshold: the module keeps it flagged as met until trailing-nexus rules would release it (manual in release 1), and never silently downgrades a crossed state.

* Exactly hitting the threshold counts as met (the test is ≥, not \>).

* A manually-marked state (physical nexus) shows as having nexus regardless of the numeric verdict.

**Acceptance criteria**

1. Each state's verdict uses its own AND/OR/sales-only logic, sourced from the rule engine.

2. The verdict is met when qualifying activity is ≥ the threshold under that logic.

3. Approaching is shown at or above the configured warning fraction before a crossing.

4. The first crossing stamps an immutable met-date and raises a crossing alert.

5. A crossed state is never silently downgraded when sales later dip.

## **F7   Agency setup**

**Goal**

Turn the insight into action: from a met (or at-risk) state, let the user register the state's tax agency and switch on tax calculation — without re-entering anything.

**Primary user story**

As a bookkeeper, I want to go from a triggered state straight into setting up its tax agency, so that collection starts without re-keying anything.

**Functional logic**

* The column reflects the state's agency status: not set up, set up (registered), or a call to action to begin. It reads and writes nexus\_agency\_registration.

* Starting setup opens the Sales Tax module's agency registration for that state, pre-filled with the state, a suggested collection start date (today or the crossing date), and a filing-frequency prompt. See §13.

* On completion, the state is marked registered here (check appears, row pins to top), and the Sales Tax module begins calculating tax on new invoices shipped to that state.

* A manual "I already have nexus here" action marks the state without a numeric crossing (physical presence), and offers the same agency-setup handoff.

**On-screen behaviour**

* Unset states show a clear "Set up" affordance; set-up states show their status and a link to manage the agency.

* The handoff is a continuation, not a new island — the user returns to the dashboard with the state updated.

**Edge cases**

* If an agency already exists for the state (created elsewhere in Sales Tax), the module links to it rather than duplicating.

* Collection start date defaults sensibly but is editable, because a business may choose to begin collecting from a specific date.

**Acceptance criteria**

1. From a state row the user can start agency setup, pre-filled with that state.

2. Completing setup marks the state registered here and enables tax calculation for it in Sales Tax.

3. Manual nexus marking is possible and offers the same handoff.

4. Existing agencies are linked, never duplicated.

## **F8   Last updated**

**Goal**

Tell the user how fresh each row is, so they can trust the number and know a recent sale may not yet be reflected.

**Functional logic**

* Shows last\_evaluated\_at for the state — the timestamp of the last recalculation that produced the row.

* Updated whenever the engine recomputes the state, whether by the nightly run, an incremental update from a new sale, or an on-demand refresh (F12).

**On-screen behaviour**

* Shown as a relative or absolute time per the product's conventions; the tooltip gives the exact timestamp.

* A manual "refresh" control lets the user force a recalculation and watch the timestamp update.

**Edge cases**

* If a recalculation is in progress, the row indicates "updating" rather than showing a stale time as if final.

**Acceptance criteria**

1. Each row shows the timestamp of its last recalculation.

2. The timestamp advances after nightly, incremental, and on-demand recalculations.

3. An in-progress recalculation is visibly indicated.

## **F9   Inline help & education**

**Goal**

Make a genuinely confusing tax topic approachable inside the product, so a non-expert owner can act with confidence and an accountant can confirm the definitions we use.

**Functional logic**

* Every column header carries a concise tooltip defining what it measures, drawn from the glossary (§6) so wording stays consistent.

* A prominent "learn more about economic nexus" entry links to a short explainer covering the ideas in §2 in plain language.

* Contextual help in the detail view (F11) explains that state's specific rule and window.

**On-screen behaviour**

* Tooltips are keyboard- and screen-reader accessible, not hover-only.

* Help content is versioned alongside the rule set so explanations track the current law.

**Acceptance criteria**

1. Each column header exposes an accessible tooltip with its definition.

2. A learn-more explainer is reachable from the dashboard.

3. Help wording matches the glossary and current rules.

## **F10   Approaching & met alerts**

**Goal**

Move the module from passive to proactive: warn the user before they cross a threshold, and tell them the instant they do — the single most valuable thing the module can do.

**Primary user story**

As an owner, I want an alert when I'm approaching or have crossed a state's threshold, so that I can act within the state's filing window rather than discovering it in an audit.

**Functional logic**

* **Approaching alert:** raised the first time a state reaches the configured warning fraction (default 80%) of a threshold that could trigger nexus there.

* **Crossing alert:** raised the first time a state's threshold is met (the moment F6 flips to met and the met-date is stamped).

* Each alert is written once per state per crossing to nexus\_alert\_log so it isn't re-fired on every recalculation.

* Alerts surface in the in-product notification centre and the business feed; email/digest delivery is a configurable extension.

* Each alert links straight to the state's detail view and its agency-setup action.

**On-screen behaviour**

* Alerts are actionable, not just informational — one tap reaches the next step.

* The user can acknowledge an alert; acknowledgement is recorded for the audit trail.

**Edge cases**

* If several states cross around the same time (e.g. after a bulk import), alerts are grouped to avoid noise while preserving one record per state.

* A state that drops back below the warning fraction and later re-approaches raises a fresh approaching alert for the new episode, without duplicating the original crossing record.

**Acceptance criteria**

1. An approaching alert fires once when a state first reaches the warning fraction.

2. A crossing alert fires once when a state's threshold is first met.

3. Alerts are de-duplicated per state per episode via the alert log.

4. Every alert links to the state detail and its agency-setup action.

## **F11   State detail view**

**Goal**

Let anyone who wants to understand a status see exactly how it was reached — the rule, the window, the numbers, the percentages, and the next step — in one place.

**Primary user story**

As an accountant, I want to open a state and see how its number was calculated and what its rule is, so that I trust the status and can advise precisely.

**Functional logic**

* Presents the state's full rule: sales threshold, transaction threshold (if any), combination logic, includable-sales basis, and measurement-period type.

* Shows the resolved window, the summed qualifying sales and the transaction count, and each as a percentage of its threshold.

* States the verdict and which test(s) drove it, the met-date if crossed, and the registration/agency status.

* Offers the agency-setup handoff (F7) and the manual-nexus toggle.

* Optionally lists the contributing transactions (drill-through) for reconciliation and audit.

**On-screen behaviour**

* Reads top-to-bottom as a short narrative: here's the rule, here's your activity, here's the verdict, here's what to do.

**Acceptance criteria**

1. The view shows the state's full rule and resolved window.

2. It shows sales and transactions with percentages of their thresholds.

3. It states the verdict, the driving test(s), and the met-date if any.

4. It offers agency setup and manual-nexus actions, and can drill to contributing transactions.

## **F12   Recalculation engine**

**Goal**

Keep every row accurate and current at a cost the system can sustain, so the dashboard is trustworthy without recomputing the world on every page load.

**Functional logic**

* **Nightly full run:** recompute every state for every active business, refresh windows for the new date, and stamp last-evaluated times.

* **Incremental update:** when a sale is created, edited, refunded, or voided, re-evaluate only the affected state(s) for that business so a crossing is caught promptly.

* **On-demand refresh:** a user-triggered recompute of a state or the whole dashboard (F8), for when someone wants the number now.

* **Rule-change reprocessing:** when the rule set changes (a state amends its law), re-evaluate affected states so verdicts reflect the new rule from its effective date.

* Each run reads sales via the aggregation logic (§12), applies the rule engine, upserts status rows, and raises any new alerts through F10 — never firing a duplicate alert.

**Non-functional notes**

* Aggregation is backed by incremental per-state rollups so a full run does not rescan the entire sales ledger from scratch each night (see §18).

* Runs are idempotent: re-running over the same data yields the same status and no duplicate alerts.

**Acceptance criteria**

1. A nightly run refreshes all states, windows, and timestamps for active businesses.

2. Creating/editing/refunding/voiding a sale re-evaluates the affected state(s) promptly.

3. On-demand refresh recomputes and updates the last-updated time.

4. A rule change re-evaluates affected states from the change's effective date.

5. Runs are idempotent and never emit duplicate alerts.

# **9   State-by-state threshold reference data**

This is the seed data for the rule engine (§11, §12). It lists each state's sales threshold, transaction threshold, and combination logic. The module stores this as maintained, versioned reference data — not as constants buried in code — because states change these rules regularly.

| REFERENCE-DATA CURRENCY — READ BEFORE BUILDING The figures below were compiled from public sources as of October 2025, with confirmed 2025–2026 changes noted (for example, Illinois removing its transaction test effective January 1, 2026; Utah and Alaska removing theirs earlier). Do not treat this table as legal advice or as permanently accurate. The rule engine must carry effective-dated versions and be updated as laws change; §18 makes that a standing requirement rather than a one-time load. |  |  |  |  |
| :---- | :---- | :---- | :---- | :---- |
| **State** | **Sales** | **Txns** | **Logic** | **Notes** |
| **Alabama** | $250,000 | — | Sales only | No transaction test. |
| **Alaska** | $100,000 | — | Sales only | No statewide sales tax; local tax administered centrally for remote sellers. Transaction test removed Jan 1, 2025\. |
| **Arizona** | $100,000 | — | Sales only | — |
| **Arkansas** | $100,000 | 200 | OR | — |
| **California** | $500,000 | — | Sales only | Higher dollar threshold; no transaction test. |
| **Colorado** | $100,000 | — | Sales only | — |
| **Connecticut** | $100,000 | 200 | **AND** | Both tests must be met. |
| **Delaware** | — | — | No sales tax | No statewide sales tax — not evaluated. |
| **District of Columbia** | $100,000 | 200 | OR | Treated as a state for tracking. |
| **Florida** | $100,000 | — | Sales only | — |
| **Georgia** | $100,000 | 200 | OR | — |
| **Hawaii** | $100,000 | 200 | OR | General excise tax functions as the sales tax. |
| **Idaho** | $100,000 | — | Sales only | — |
| **Illinois** | $100,000 | — | Sales only | Transaction test removed effective Jan 1, 2026\. |
| **Indiana** | $100,000 | — | Sales only | — |
| **Iowa** | $100,000 | — | Sales only | — |
| **Kansas** | $100,000 | — | Sales only | — |
| **Kentucky** | $100,000 | 200 | OR | — |
| **Louisiana** | $100,000 | — | Sales only | — |
| **Maine** | $100,000 | — | Sales only | — |
| **Maryland** | $100,000 | 200 | OR | — |
| **Massachusetts** | $100,000 | — | Sales only | — |
| **Michigan** | $100,000 | 200 | OR | — |
| **Minnesota** | $100,000 | 200 | OR | — |
| **Mississippi** | $250,000 | — | Sales only | — |
| **Missouri** | $100,000 | — | Sales only | Economic nexus effective Jan 1, 2023\. |
| **Montana** | — | — | No sales tax | No statewide sales tax — not evaluated. |
| **Nebraska** | $100,000 | 200 | OR | — |
| **Nevada** | $100,000 | 200 | OR | — |
| **New Hampshire** | — | — | No sales tax | No statewide sales tax — not evaluated. |
| **New Jersey** | $100,000 | 200 | OR | — |
| **New Mexico** | $100,000 | — | Sales only | Gross receipts tax functions as the sales tax. |
| **New York** | $500,000 | 100 | **AND** | Both tests must be met; transaction test is 100\. |
| **North Carolina** | $100,000 | — | Sales only | — |
| **North Dakota** | $100,000 | — | Sales only | — |
| **Ohio** | $100,000 | 200 | OR | — |
| **Oklahoma** | $100,000 | — | Sales only | — |
| **Oregon** | — | — | No sales tax | No statewide sales tax — not evaluated. |
| **Pennsylvania** | $100,000 | — | Sales only | — |
| **Rhode Island** | $100,000 | 200 | OR | — |
| **South Carolina** | $100,000 | — | Sales only | — |
| **South Dakota** | $100,000 | — | Sales only | The Wayfair state; transaction test since removed. |
| **Tennessee** | $100,000 | — | Sales only | — |
| **Texas** | $500,000 | — | Sales only | Higher dollar threshold; no transaction test. |
| **Utah** | $100,000 | — | Sales only | Transaction test removed Jul 1, 2025\. |
| **Vermont** | $100,000 | 200 | OR | — |
| **Virginia** | $100,000 | 200 | OR | — |
| **Washington** | $100,000 | — | Sales only | — |
| **West Virginia** | $100,000 | 200 | OR | — |
| **Wisconsin** | $100,000 | — | Sales only | — |
| **Wyoming** | $100,000 | — | Sales only | Transaction test since removed. |

| How the engine uses this: for each row, if Logic is "No sales tax" the state is displayed but never evaluated. Otherwise, the sales figure is the dollar threshold and Txns is the transaction threshold (blank means no transaction test). Logic tells the verdict function whether to combine the two tests with AND, OR, or to use the sales test alone. Notes and effective dates travel with the version so history stays explainable. |
| :---- |

# **10   End-to-end user flows**

The features above, stitched into the journeys users actually take. Each flow lists the steps and the system's part in them.

## **10.1   First look — reviewing exposure**

Priya opens the Nexus dashboard for the first time after selling into several states.

1. Priya opens Nexus from the Sales Tax area.

2. The engine has already run; the dashboard shows every state with her sales, transaction counts, windows, and verdicts. States she's registered in sit at the top with a check.

3. She scans the Threshold-met column: most states read "not met", two read "approaching" in amber, one reads "met".

4. She opens the met state to understand it (flow 10.3).

## **10.2   A sale nudges a state toward its threshold**

Marcus records a large invoice to a customer in a state the business is watching.

1. Marcus creates the invoice in the Sales module; the customer's ship-to state and the items' taxability are captured.

2. The incremental recalculation re-evaluates that state for the business.

3. Qualifying sales now exceed 80% of the state's threshold, so the engine raises a one-time approaching alert and updates the row (status "approaching", new last-updated time).

4. Marcus sees the alert in the notification centre, opens the state detail, and notes he'll likely need to register soon.

## **10.3   A threshold is crossed**

Continued sales push the state over the line.

1. A further sale takes qualifying sales to or above the state's threshold under its combination logic.

2. The engine flips the verdict to met, stamps an immutable met-date, and raises a one-time crossing alert.

3. The dashboard row turns to "met" and shows a call to action toward agency setup.

4. Marcus opens the alert, reviews the detail view (rule, window, numbers, percentages), and clicks through to set up the agency (flow 10.4).

## **10.4   Registering and turning on collection**

From a met state, the business registers and starts collecting.

1. From the state row (or its detail view), Marcus starts agency setup.

2. The Sales Tax module's agency registration opens, pre-filled with the state, a suggested collection start date, and a filing-frequency prompt.

3. Marcus enters the state permit details and filing frequency and completes setup.

4. The state is marked registered in Nexus (check appears, row pins to top); Sales Tax now calculates tax on new invoices shipped to that state.

5. From here on, tax collected on those invoices posts to Sales Tax Payable (see §14).

## **10.5   Manually marking physical nexus**

The business opens a warehouse in a state — physical nexus that no sales figure would reveal.

1. Marcus opens the state and chooses "I already have nexus here".

2. The state is marked as having nexus regardless of its numeric verdict, pins to the top, and offers agency setup.

3. He completes agency setup as in flow 10.4, and collection begins.

## **10.6   Advising a client (accountant)**

Elena reviews a client's exposure through the accountant tools.

1. Elena opens the client's Nexus dashboard.

2. She runs the exposure report (§15) to see all states, activity, percentages, and verdicts in one artefact.

3. For any state she checks the detail view for the exact rule and window, and the threshold-history report for when crossings occurred.

4. She advises the client which states to register in and confirms the books reflect collection where it has begun.

# **11   Data model & schema**

A proposed logical model. Types are indicative; map them to the platform's conventions. The model separates maintained reference data (the state rules) from per-business computed state (the status rows), from registration facts, from the alert log. Everything is scoped to a business.

## **11.1   Entities at a glance**

| Entity | Kind | Holds |
| :---- | :---- | :---- |
| nexus\_state\_rule | Reference (versioned) | One state's thresholds, combination logic, includable basis, and period type, effective-dated. |
| nexus\_state\_status | Computed per business | The current row for a business × state: window, sales, count, verdict, status, timestamps. |
| nexus\_agency\_registration | Fact per business | Whether/when a business registered (or manually marked) a state, and its filing details. |
| nexus\_alert\_log | Append-only per business | Each approaching/crossing alert raised, for de-duplication and audit. |
| nexus\_settings | Config per business | Warning fraction, alert channels, and marketplace-inclusion preferences. |

## **11.2   Entity detail**

### **nexus\_state\_rule**

*Purpose.* The maintained rule set from §9. Effective-dated so a state's history of rule changes is preserved and verdicts can be reproduced for any date.

| Field | Type | Description |
| :---- | :---- | :---- |
| id | uuid | Primary key. |
| state\_code | char(2) | Two-letter code — the stable key used everywhere (e.g. NY, CA). |
| state\_name | text | Display name. |
| has\_sales\_tax | boolean | False for no-sales-tax states; when false the state is shown but never evaluated. |
| sales\_threshold | money / null | Dollar threshold (e.g. 100000). Null only where not applicable. |
| txn\_threshold | integer / null | Transaction threshold (e.g. 200). Null where the state has no transaction test. |
| combination\_logic | enum | OR | AND | SALES\_ONLY — how the two tests combine. |
| includable\_sales\_basis | enum | GROSS | RETAIL | TAXABLE — which sales count toward the dollar threshold. |
| measurement\_period\_type | enum | CURRENT\_YEAR | PREVIOUS\_YEAR | CURRENT\_OR\_PREVIOUS\_YEAR | TRAILING\_12M. |
| trailing\_nexus\_rule | text / enum | How long the obligation persists after sales fall away (informational in release 1). |
| effective\_from | date | Date this rule version takes effect. |
| effective\_to | date / null | Date this version is superseded; null if current. |
| notes | text | Human context (e.g. "transaction test removed 2026"). |

### **nexus\_state\_status**

*Purpose.* The computed dashboard row for one business and one state. Upserted by the recalculation engine (§12).

| Field | Type | Description |
| :---- | :---- | :---- |
| id | uuid | Primary key. |
| business\_id | uuid | Owning business (tenant scope). |
| state\_code | char(2) | The state this status is for. |
| window\_start | date | Resolved start of the measurement window. |
| window\_end | date | Resolved end of the measurement window. |
| sales\_amount | money | Qualifying sales into the state over the window (per includable basis). |
| taxable\_sales\_amount | money | Taxable-only subtotal, retained for reporting and reconciliation. |
| txn\_count | integer | Qualifying transaction count over the window. |
| pct\_of\_sales\_threshold | decimal | sales\_amount ÷ sales\_threshold (0–1+), for the detail view and alerts. |
| pct\_of\_txn\_threshold | decimal / null | txn\_count ÷ txn\_threshold where applicable. |
| threshold\_met | boolean | The verdict under the state's combination logic. |
| status | enum | NOT\_APPROACHING | APPROACHING | MET | REGISTERED. |
| threshold\_met\_date | date / null | Immutable date the threshold was first met. |
| last\_evaluated\_at | timestamp | When this row was last recalculated (drives F8). |
| updated\_at | timestamp | Row maintenance timestamp. |

### **nexus\_agency\_registration**

*Purpose.* The registration fact linking a state to a tax agency, plus manual nexus marking. Written by the agency-setup handoff (F7) and read for sorting and the check marker.

| Field | Type | Description |
| :---- | :---- | :---- |
| id | uuid | Primary key. |
| business\_id | uuid | Owning business. |
| state\_code | char(2) | The registered/marked state. |
| tax\_agency\_id | uuid / null | Link to the Sales Tax module's agency, once created. |
| registration\_type | enum | ECONOMIC | PHYSICAL\_MANUAL — how nexus was established. |
| registration\_status | enum | NOT\_STARTED | REGISTERED. |
| sales\_tax\_permit\_number | text / null | State-issued permit number, if captured. |
| filing\_frequency | enum / null | MONTHLY | QUARTERLY | ANNUAL. |
| collection\_start\_date | date | When tax calculation begins for the state. |
| created\_at | timestamp | Record creation time. |

### **nexus\_alert\_log**

*Purpose.* Append-only record of alerts, used to fire each alert exactly once per episode and to provide an audit trail.

| Field | Type | Description |
| :---- | :---- | :---- |
| id | uuid | Primary key. |
| business\_id | uuid | Owning business. |
| state\_code | char(2) | The alerting state. |
| alert\_type | enum | APPROACHING | CROSSED. |
| episode\_key | text | Identifies the approach/crossing episode, so re-approaches don't duplicate a prior alert. |
| threshold\_pct\_at\_alert | decimal | The percentage that triggered the alert. |
| triggered\_at | timestamp | When the alert was raised. |
| acknowledged\_by | uuid / null | User who acknowledged it. |
| acknowledged\_at | timestamp / null | When acknowledged. |

### **nexus\_settings**

*Purpose.* Per-business configuration for the module's behaviour.

| Field | Type | Description |
| :---- | :---- | :---- |
| business\_id | uuid | Owning business (primary key). |
| warning\_fraction | decimal | Approaching threshold fraction (default 0.80). |
| alert\_channels | json | Where alerts are delivered (in-app, email/digest). |
| include\_marketplace\_in\_measurement | boolean | Whether facilitator-channel sales count toward measurement (default true). |

## **11.3   Relationships**

* nexus\_state\_status and nexus\_agency\_registration are child records of a business and reference a state\_code that resolves to the current nexus\_state\_rule version for that date.

* nexus\_agency\_registration.tax\_agency\_id links into the Sales Tax module's agency, which in turn drives rate calculation and the Sales Tax Payable liability (§13, §14).

* nexus\_alert\_log references a business and state and is never updated except to record acknowledgement.

* Sales are not duplicated here — the engine reads them from the Sales module at calculation time and stores only the aggregates in nexus\_state\_status.

# **12   Calculation logic & algorithms**

The precise logic behind every number and verdict. Pseudocode is illustrative; the rules it encodes are binding.

## **12.1   Resolving the measurement window**

Given a state rule and today's date, resolve the concrete window over which activity is measured.

| function resolveWindow(rule, today):     switch rule.measurement\_period\_type:         case CURRENT\_YEAR:             return { start: Jan 1 of today.year, end: today }         case PREVIOUS\_YEAR:             return { start: Jan 1 of (today.year \- 1), end: Dec 31 of (today.year \- 1\) }         case CURRENT\_OR\_PREVIOUS\_YEAR:             // measure the span that can capture a crossing in either year             return { start: Jan 1 of (today.year \- 1), end: today }         case TRAILING\_12M:             return { start: today minus 12 months \+ 1 day, end: today } |
| :---- |

## **12.2   Aggregating sales and counting transactions**

Sum qualifying sales and count qualifying transactions for a business × state over the window, honouring the state's includable-sales basis and the ship-to attribution rule.

| function aggregate(business, rule, window):     txns \= salesModule.qualifyingSales(business, window)   // invoices \+ sales receipts     salesSum \= 0 ; count \= 0     for each line in txns.lines:         state \= shipToState(line)         // ship-to; fallback billing state; fallback home state         if state \!= rule.state\_code: continue         if include(line, rule.includable\_sales\_basis):             salesSum \+= homeCurrency(line.netAmount)   // net of refunds/returns     for each txn in txns:         if txn attributes to rule.state\_code and not voided and not fully refunded:             count \+= 1     // marketplace channel: included per nexus\_settings; excluded from what the business itself collects     return { salesSum, count }   function include(line, basis):     switch basis:         case GROSS:   return true                         // all sales count         case RETAIL:  return not line.isForResale         // exclude sales for resale         case TAXABLE: return line.isTaxable               // exclude exempt sales |
| :---- |

| ATTRIBUTION AND NETTING RULES Ship-to state is the primary attribution. If a transaction has no ship-to (e.g. a service with only a billing address), use the billing state; if neither exists, use the business's home state. The chosen rule is applied identically in the Sales Tax module so figures reconcile. Netting: refunds, credit notes, and returns reduce the sales sum; a fully refunded or voided transaction is excluded from both the sum and the count; a partially refunded transaction remains one transaction and contributes its net amount. Currency: each line is converted to the business's home currency at the transaction's recorded rate before summing. |
| :---- |

## **12.3   Evaluating the threshold verdict**

Apply the state's combination logic to the aggregates. This is the function the whole dashboard turns on.

| function evaluate(agg, rule):     metBySales \= (rule.sales\_threshold \!= null) and (agg.salesSum \>= rule.sales\_threshold)     metByTxn   \= (rule.txn\_threshold  \!= null) and (agg.count    \>= rule.txn\_threshold)       switch rule.combination\_logic:         case SALES\_ONLY: met \= metBySales         case OR:         met \= metBySales or metByTxn         case AND:        met \= metBySales and metByTxn       pctSales \= rule.sales\_threshold ? agg.salesSum / rule.sales\_threshold : 0     pctTxn   \= rule.txn\_threshold   ? agg.count    / rule.txn\_threshold   : null     return { met, pctSales, pctTxn } |
| :---- |

**Note on ≥.** The tests use "greater than or equal to": exactly reaching a threshold means it is met. AND states require both component tests true; a high transaction count alone never establishes nexus in an AND state — the guard that protects the New York sticker-seller case in §2.3.

## **12.4   Deriving the display status**

Translate the verdict, the percentages, and any registration into the four-value status the dashboard shows.

| function deriveStatus(evalResult, registration, settings):     if registration.registration\_status \== REGISTERED        or registration.registration\_type \== PHYSICAL\_MANUAL:         return REGISTERED     if evalResult.met:         return MET     approachingBySales \= evalResult.pctSales \>= settings.warning\_fraction     approachingByTxn   \= evalResult.pctTxn \!= null                          and canTxnTrigger(rule)          // not an AND-only-sales situation                          and evalResult.pctTxn \>= settings.warning\_fraction     if approachingBySales or approachingByTxn:         return APPROACHING     return NOT\_APPROACHING |
| :---- |

## **12.5   Detecting crossings and raising alerts**

On each evaluation, compare against the prior status to fire alerts exactly once per episode.

| function onEvaluated(prev, curr, business, state, settings):     // crossing: newly met     if curr.threshold\_met and not prev.threshold\_met:         curr.threshold\_met\_date \= coalesce(prev.threshold\_met\_date, today)   // immutable once set         if not alertExists(business, state, CROSSED, curr.episode\_key):             raiseAlert(business, state, CROSSED, curr.pctSales)       // approaching: newly at/over warning fraction and not yet met     if curr.status \== APPROACHING and prev.status \== NOT\_APPROACHING:         if not alertExists(business, state, APPROACHING, curr.episode\_key):             raiseAlert(business, state, APPROACHING, curr.pctSales)       upsert nexus\_state\_status(curr) |
| :---- |

**Episode key.** An episode groups a single approach-then-cross sequence. If a state's activity later falls well below the warning fraction and rises again, a new episode key is minted so a genuinely new approach can alert again — without ever re-firing the original crossing record or duplicating within one episode.

## **12.6   When recalculation runs**

| Trigger | Scope | Why |
| :---- | :---- | :---- |
| Nightly batch | All states, all active businesses | Refresh windows for the new date; catch anything time-based. |
| Sale created / edited / refunded / voided | The affected state(s) for that business | Catch a crossing promptly, near real time. |
| User on-demand refresh | A state or the whole dashboard | Give an immediate, current answer. |
| Rule-set change | States whose rule changed, from the effective date | Keep verdicts aligned to current law. |

| Idempotency: every path runs the same evaluate → deriveStatus → onEvaluated sequence and is safe to repeat. Re-running over unchanged data yields identical status rows and raises no duplicate alerts, because alerts are guarded by the alert log and the episode key. |
| :---- |

# **13   Integration with other modules**

Nexus is not an island — it reads from the modules that already exist and hands off to the ones that act. This section defines those seams.

| Module | Direction | What flows across the seam |
| :---- | :---- | :---- |
| **Sales / Invoicing** | reads | Recorded invoices and sales receipts: amounts, dates, line items, and the ship-to link. The sole source of the activity being measured. |
| **Customers** | reads | The ship-to (and billing) address that determines a sale's state. Accurate customer addresses are a prerequisite for accurate nexus. |
| **Products & Services** | reads | Each item's taxability (taxable / exempt / for-resale), which drives the includable-sales basis in §12.2. |
| **Sales Tax** | reads \+ writes | The agency-setup handoff creates/links a tax agency and turns on rate calculation for a state; Nexus reads registration status back for sorting and markers. |
| **Expenses** | context | Purchases don't establish sales-tax nexus, so Expenses is not a measurement source. (Use-tax on purchases is a separate Sales Tax concern; noted, not handled here.) |
| **Reports** | writes | Nexus exposure, approaching-risk, and threshold-history reports surface through the reporting area (§15). |
| **Notifications / Business feed** | writes | Approaching and crossing alerts (F10) are delivered here. |

## **13.1   The Sales Tax handoff in detail**

This is the most consequential seam, so it is worth being explicit.

1. Nexus flags a state as met (or the user chooses to register a watched/marked state).

2. The user starts agency setup; Nexus passes the state code, a suggested collection start date, and the registration type to the Sales Tax module.

3. Sales Tax creates or links the state's tax agency, captures the permit number and filing frequency, and records the collection start date.

4. Sales Tax enables rate calculation for that state; from the collection start date, new invoices shipped there carry tax.

5. Nexus reads the resulting registration back, marks the state registered, and pins it to the top of the dashboard.

| DATA-QUALITY DEPENDENCY The measurement is only as good as the addresses and taxability behind it. If customers lack ship-to states, or items lack a taxability setting, sales can be mis-attributed or mis-counted. The module should surface a gentle data-quality prompt when a material volume of sales cannot be attributed to a state, so users can fix the source data rather than trust a wrong number. |
| :---- |

# **14   Accounting treatment**

| THE ONE THING TO INTERNALISE FIRST Nexus monitoring creates no journal entries. Watching sales cross a threshold is a compliance signal, not an accounting event — nothing posts to the ledger when a state turns "met". The accounting begins one step later, when the business registers and the Sales Tax module starts collecting tax on invoices, and continues when that tax is remitted to the state. This section documents that full lifecycle so there is no confusion about what posts, when, and where. |
| :---- |

## **14.1   Accounts involved**

| Account | Type | Role |
| :---- | :---- | :---- |
| **Accounts Receivable** | Asset | What customers owe on invoices, tax included, until they pay. |
| **Bank / Cash** | Asset | Where customer payments land and from which remittances are paid. |
| **Sales Revenue** | Income | The pre-tax value of goods/services sold. |
| **Sales Tax Payable** | Liability | Tax collected from customers, held until remitted. Ideally tracked per state/agency. |
| **Sales Tax Vendor Compensation** | Income / contra-expense | Optional: a small discount some states allow for filing on time. |

## **14.2   Recording a taxable sale (after registration)**

Once a state is registered and collection is on, an invoice into that state carries tax. Example: a $1,000 sale with 8% state sales tax.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Accounts Receivable | $1,080.00 |  |
| Sales Revenue |  | $1,000.00 |
| Sales Tax Payable — *State* |  | $80.00 |

*Effect:* revenue is recognised at the pre-tax amount; the $80 collected is not income — it is a liability the business owes the state. The customer's total receivable is $1,080.

## **14.3   Customer payment**

When the customer pays the invoice, the receivable clears to the bank. The tax liability is unaffected — it stays on the books until remitted.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Bank / Cash | $1,080.00 |  |
| Accounts Receivable |  | $1,080.00 |

## **14.4   Refund or return of a taxable sale**

A refund reverses both the revenue and the tax proportionally, which also nets down the figures the Nexus engine measures (§12.2). Example: the $1,000 sale above is fully refunded.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Sales Revenue (or Sales Returns) | $1,000.00 |  |
| Sales Tax Payable — *State* | $80.00 |  |
| Bank / Cash (or A/R) |  | $1,080.00 |

*Effect:* the liability to the state is reduced by the tax no longer owed, and the customer is made whole.

## **14.5   Remitting tax to the state**

On the filing schedule, the business pays the accumulated liability to the state agency. This clears Sales Tax Payable for that state. Example: remitting $80 collected.

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Sales Tax Payable — *State* | $80.00 |  |
| Bank / Cash |  | $80.00 |

**Timely-filing discount (optional).** Some states let a business keep a small percentage for filing on time. If the state allows, say, a $2 discount on an $80 liability, the remittance recognises that as income:

| Account | Debit | Credit |
| :---- | ----- | ----- |
| Sales Tax Payable — *State* | $80.00 |  |
| Bank / Cash |  | $78.00 |
| Sales Tax Vendor Compensation |  | $2.00 |

## **14.6   Exposure before registration (advanced, future)**

There is a real accounting question the module deliberately does not auto-post in release 1: what if a business crossed a state's threshold and kept selling without collecting tax? It may owe that uncollected tax out of its own pocket — a contingent liability. Because the amount is an estimate and depends on judgement (taxability, whether the state will assess, voluntary-disclosure outcomes), the module treats it as an insight, not an automatic journal entry.

* **Release 1:** surface the exposure as information (the state is "met" but unregistered, with the sales that occurred after the crossing visible in the detail view). No posting.

* **Future (§4.3):** optionally let the user record an estimated liability, which would post as a debit to a sales-tax expense/contingency account and a credit to an estimated sales-tax liability — clearly labelled as an estimate and reversible.

## **14.7   Ledger view and reconciliation**

Because collected tax accumulates in Sales Tax Payable per state, the general ledger for that account is the running record of what is owed and what has been remitted.

| Date | Description | Debit | Credit | Balance |
| :---- | :---- | ----- | ----- | ----- |
| — | Opening balance — State X |  |  | $0.00 |
| — | Tax collected on invoices |  | $80.00 | $80.00 |
| — | Tax reversed on a refund | $8.00 |  | $72.00 |
| — | Remittance to State X | $72.00 |  | $0.00 |

| CASH VS. ACCRUAL The postings above assume accrual accounting, where tax is recognised as a liability when the invoice is issued. On a cash basis the liability is generally recognised when payment is received. The Sales Tax module owns this behaviour and the Sales Tax Liability report reflects the business's method; Nexus itself measures sales activity for the threshold and does not change the accounting basis. |
| :---- |

# **15   Reporting**

The reports that turn the module's data into artefacts a user can review, share, and keep for audit.

## **15.1   Economic Nexus Exposure report**

The dashboard as a report: every state with its window, qualifying sales, transaction count, percentages of thresholds, verdict, and registration status. The primary artefact for a periodic exposure review.

| Column | Meaning |
| :---- | :---- |
| State | Jurisdiction. |
| Window | Resolved measurement period. |
| Sales / % of threshold | Qualifying sales and how close to the dollar threshold. |
| Transactions / % of threshold | Count and how close to the transaction threshold (if any). |
| Verdict | Not met / approaching / met. |
| Registration | Not started / registered / manually marked; met-date if crossed. |

## **15.2   Approaching-Risk report**

A focused list of states at or above the warning fraction but not yet met — the "act soon" worklist. Sorted by proximity so the most urgent state is first.

## **15.3   Threshold-History (audit trail)**

An immutable record of when each state was first met and when each alert was raised and acknowledged, sourced from the met-date and the alert log. This is the artefact an accountant reaches for if a state ever questions when collection should have begun.

## **15.4   Relationship to the Sales Tax Liability report**

Nexus reports answer "where and when am I obligated?"; the Sales Tax Liability report (owned by the Sales Tax module) answers "how much tax have I collected and owe per agency?". They must reconcile: the qualifying sales the Nexus engine measures for a state and period should tie back to the sales underlying that state's liability. Section 12.2's shared attribution and netting rules are what make the two agree.

# **16   Notifications & automation rules**

| Event | Trigger | Delivery | Action offered |
| :---- | :---- | :---- | :---- |
| **Approaching** | State first reaches the warning fraction (default 80%). | In-app \+ business feed (email/digest configurable). | Open state detail; review and prepare. |
| **Crossed** | State's threshold first met. | In-app \+ business feed (email/digest configurable). | Open state detail; start agency setup. |
| **Registered** | Agency setup completed for a state. | In-app confirmation. | View agency; confirm collection is on. |
| **Data-quality** | Material sales cannot be attributed to a state. | In-app prompt. | Fix customer addresses / item taxability. |
| **Rule change** | A tracked state's rule is updated in the engine. | Optional in-app note on affected states. | Review any changed verdicts. |

* Each alert is written once per state per episode (via the alert log and episode key), so recalculations never spam the user.

* Alerts are actionable — every one links to the next step.

* Acknowledgements are recorded for the audit trail (§15.3).

# **17   Business rules & edge cases**

A consolidated reference of the rules scattered through the spec, plus the corner cases QA should probe.

| \# | Rule / edge case | Expected behaviour |
| :---- | :---- | :---- |
| 1 | No-sales-tax states | Shown for completeness, marked not applicable, never evaluated. |
| 2 | Threshold reached exactly | Counts as met (test is ≥, not \>). |
| 3 | AND-logic states | Both tests must pass; a high transaction count alone never triggers nexus. |
| 4 | Includable-sales basis | Sum gross, retail, or taxable sales per the state's rule — not always all sales. |
| 5 | Ship-to attribution | Ship-to state first; fallback billing state; fallback home state — applied identically to tax calc. |
| 6 | Refunds / returns | Net down sales and the liability; fully refunded/voided transactions excluded from sum and count. |
| 7 | Multi-currency sales | Converted to home currency at the transaction's rate before summing. |
| 8 | Crossed then sales dip | Stays flagged met; never silently downgraded (trailing nexus). Release 1 releases it manually. |
| 9 | Manual physical-nexus mark | State treated as having nexus regardless of numeric verdict; pins to top. |
| 10 | Marketplace-channel sales | Included in measurement by default (configurable); excluded from what the business itself collects. |
| 11 | Year-boundary reset | Current-year windows reset as the calendar advances; the engine recomputes windows. |
| 12 | Mid-year onboarding | Measures only the sales Pilucent holds; flags that history may be incomplete. |
| 13 | Duplicate-alert prevention | One alert per state per episode via the alert log and episode key. |
| 14 | Rule change mid-period | Effective-dated rules; verdicts follow the new rule from its effective date. |
| 15 | Existing agency for a state | Link to it; never create a duplicate agency. |

# **18   Non-functional requirements**

## **18.1   Performance & scale**

* Aggregation is backed by incremental per-state rollups so the nightly run and incremental updates never rescan the full sales ledger from scratch.

* The dashboard reads pre-computed status rows; it does not aggregate live on page load.

* Incremental recalculation after a sale is near real time so crossings are caught promptly.

## **18.2   Data currency & maintenance**

* **Standing requirement:** the state-rule set is maintained reference data. Every confirmed statutory change must be entered as an effective-dated rule version before it takes effect. This is ongoing operational work, not a one-time seed.

* Rule versions are auditable: any past verdict can be reproduced from the rule version in effect on that date.

## **18.3   Auditability**

* Met-dates and the alert log are immutable history; acknowledgements are recorded.

* The threshold-history report (§15.3) provides a defensible record of when obligations arose.

## **18.4   Security & tenancy**

* All Nexus data is scoped to a business; no cross-tenant access. Accountant access follows the existing accountant-tools permission model.

## **18.5   Accessibility**

* Status is never conveyed by colour alone — colour is paired with text and an icon. Tooltips are keyboard- and screen-reader accessible.

## **18.6   Localisation & coverage**

* Release 1 covers U.S. states plus the District of Columbia. Additional local jurisdictions (e.g. home-rule localities) and territories are future coverage, added as rule versions without code changes.

# **19   Assumptions, dependencies & risks**

## **19.1   Assumptions**

* Sales recorded in Pilucent are the complete picture of the business's sales for the states measured; channels not synced are out of scope for accuracy.

* Customer records carry usable ship-to (or billing) addresses, and items carry a taxability setting.

* The Sales Tax module owns rate calculation, agencies, filing frequency, and the accounting basis; Nexus consumes and hands off to it.

## **19.2   Dependencies**

* Sales, Customers, and Products & Services modules for the measured activity and its attributes.

* The Sales Tax module for the agency-setup handoff and the liability accounting.

* Notifications / business feed for alert delivery; the reporting area for the reports.

## **19.3   Risks & mitigations**

| Risk | Impact | Mitigation |
| :---- | :---- | :---- |
| State rules change and the engine falls behind | Wrong verdicts; compliance risk for users | Effective-dated rule versions; a standing maintenance process (§18.2); a rule-change note to users. |
| Incomplete or wrong source data (addresses, taxability) | Mis-attributed or mis-counted sales | Data-quality prompts (§13); reconciliation to the liability report. |
| Users read a verdict as legal advice | Over-reliance | Clear framing that figures are guidance, not legal advice; link to authoritative help. |
| Missing external-channel sales | Under-measured exposure | Scope clearly; encourage syncing channels; measure only what is held and say so. |
| Alert fatigue | Users ignore alerts | One alert per episode; grouping; actionable, prioritised delivery. |

# **20   Phased delivery plan**

A suggested build order that delivers value early and de-risks the hardest parts first.

| Phase | Scope | Outcome |
| :---- | :---- | :---- |
| **P1 — Engine & data** | Rule engine seeded from §9; aggregation, window resolution, verdict and status logic; status storage. | Correct per-state verdicts computable for a business (no UI yet). |
| **P2 — Dashboard** | The all-states dashboard (F1–F6, F8–F9), detail view (F11), recalculation triggers (F12). | Users can see and understand their exposure. |
| **P3 — Alerts** | Approaching and crossing alerts (F10) with de-duplication and acknowledgement. | The module becomes proactive. |
| **P4 — Handoff & accounting** | Agency-setup handoff (F7), Sales Tax integration, and the collection/remittance accounting path (§14). | Insight turns into action; books stay correct. |
| **P5 — Reports** | Exposure, approaching-risk, and threshold-history reports (§15). | Shareable, audit-ready artefacts. |
| **Later** | Trailing-nexus automation, marketplace automation, registration assistance, exposure quantification (§4.3). | Deeper automation and compliance depth. |

# **21   Appendix**

## **21.1   Illustrative API surface**

A sketch of the endpoints the front end would consume — indicative, to align on shape, not final contracts.

| GET  /nexus/dashboard      \-\> \[ { state, window, sales, txnCount, verdict, status,             registration, lastUpdatedAt } \]   // one row per state   GET  /nexus/state/{stateCode}      \-\> { rule, window, sales, taxableSales, txnCount,           pctSales, pctTxn, verdict, status, thresholdMetDate,           registration, contributingTransactions? }   POST /nexus/state/{stateCode}/mark-nexus      // manual physical nexus POST /nexus/state/{stateCode}/start-agency-setup      { collectionStartDate } \-\> handoff to Sales Tax agency registration   POST /nexus/recalculate            // whole dashboard, on-demand POST /nexus/state/{stateCode}/recalculate   GET  /nexus/alerts                 // approaching \+ crossed, with ack state POST /nexus/alerts/{id}/acknowledge   GET  /nexus/reports/exposure GET  /nexus/reports/approaching-risk GET  /nexus/reports/threshold-history |
| :---- |

## **21.2   Example rule-change log (why versioning matters)**

A few recent, real-world style changes that the effective-dated rule engine must absorb without a code deploy:

| State | Change | Effect on the engine |
| :---- | :---- | :---- |
| Alaska | Removed the 200-transaction test (Jan 1, 2025). | New rule version: combination\_logic becomes SALES\_ONLY from that date. |
| Utah | Removed the 200-transaction test (Jul 1, 2025). | New version: SALES\_ONLY from that date; prior verdicts preserved. |
| Illinois | Removed the transaction test (Jan 1, 2026). | New version: SALES\_ONLY from that date. |

## **21.3   Source landscape**

The threshold reference data in §9 was compiled from widely used public sales-tax references (state-by-state economic-nexus guides and charts maintained by established tax-content publishers), cross-checked for the 2025–2026 changes noted. Because these rules change, treat §9 as a snapshot to be maintained (§18.2), and confirm any specific state's current rule against that state's department of revenue before relying on it for a filing decision.

| CLOSING NOTE This module earns its keep by converting an invisible, shifting legal risk into a clear, timely status a business can act on. Build the engine correctly, keep the rule set current, keep monitoring cleanly separate from accounting, and hand off smoothly to tax collection — and the result is a feature that quietly protects every multi-state seller who uses Pilucent. |
| :---- |

