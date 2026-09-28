

| BALANZIFY PRD Advanced Subscription Management System Dynamic plans, entitlement control, employee/user limits, overage billing, add-ons, coupons, offers, referrals, free trials, upgrade and downgrade lifecycle. |
| :---- |

| Field | Details |
| :---- | :---- |
| Product | Balanzify SaaS Platform |
| Module | Advanced Subscription Management |
| Prepared For | Product, Design, Engineering, QA, Sales and Support Teams |
| Prepared Date | 08 June 2026 |
| Version | v1.0 PRD |
| Document Goal | Define the subscription engine that lets Balanzify Super Admins dynamically create and manage subscription plans, limits, modules, features, add-ons, billing rules and customer self-service subscription changes. |

Core pricing example requested: Starter plan includes 1-25 employees and up to 10 users for $150 per month. If the company needs 5 additional employees beyond the plan limit, Balanzify charges $6 per additional employee per month, making the monthly total $180.

# **Contents**

1\. Executive Summary

2\. Goals, Non-Goals and Success Metrics

3\. Market and Product Research Summary

4\. Product Scope

5\. Personas and Permissions

6\. Subscription Concepts and Terminology

7\. Pricing Strategy and Plan Structure

8\. Core Billing Logic and Calculation Rules

9\. Super Admin Panel Requirements

10\. Company Self-Service Requirements

11\. Module, Feature and Entitlement Management

12\. Coupon, Offer, Referral and Trial System

13\. Upgrade, Downgrade, Cancellation and Renewal Workflows

14\. Functional Requirements

15\. User Stories and Acceptance Criteria

16\. UX and Screen Requirements

17\. Data Model

18\. API Requirements

19\. Event, Notification and Audit Requirements

20\. Accounting, Invoice and Revenue Rules

21\. Edge Cases and Guardrails

22\. Non-Functional Requirements

23\. QA Test Plan

24\. Implementation Roadmap

25\. Open Questions and Decisions

26\. References

# **1\. Executive Summary**

Balanzify needs an advanced, dynamic subscription management system that controls how each tenant can access accounting, HR, payroll, inventory, tax, reporting, AI and support capabilities. The system must be manageable from the Super Admin panel without code changes. It must support base subscription plans, included employee and user limits, add-on overage pricing, coupon and offer logic, referral credits, free trials, upgrade/downgrade workflows, usage monitoring, payment lifecycle, invoicing, access enforcement and auditability.

The most important rule is that Balanzify should not hard-code plans. A Super Admin should be able to configure plan names, prices, billing cycles, modules, feature access, limits, add-on rates, discounts and customer eligibility from the admin panel. Companies should be able to select a plan, start a trial, upgrade, downgrade, buy additional employee capacity, manage payment methods and view invoices from their own subscription area.

Product direction: Balanzify should use a subscription entitlement engine, not only a payment page. Payment, invoice and pricing data decide what the customer has purchased; the entitlement service enforces what the customer can actually access inside the application.

# **2\. Goals, Non-Goals and Success Metrics**

## **2.1 Goals**

* **Dynamic plan configuration:** Super Admins can create, edit, archive and version plans without developer involvement.  
* **Limit-based billing:** Plans include employee/user limits and support automatic add-on charges when companies exceed included limits.  
* **Feature-level entitlement control:** Modules, menus, features and API operations are enabled based on subscription and role access.  
* **Self-service lifecycle:** Company owners can upgrade, downgrade, renew, cancel, reactivate and buy add-ons with a clear billing preview.  
* **Promotion management:** , offCouponsers, referral credits and free trials can be configured with rules, validity and redemption limits.  
* **Billing accuracy:** Proration, overage calculation, annual discounts and invoice line items are transparent and auditable.  
* **Enterprise readiness:** Support multi-currency, multiple legal entities, tax fields, region availability, audit logs, billing reports and integration with payment providers.

## **2.2 Non-Goals for MVP**

* Full marketplace revenue sharing with third-party app developers.  
* Complex revenue recognition automation under ASC 606 or IFRS 15 beyond basic invoice and ledger mapping.  
* Offline/manual bank reconciliation for subscription invoices beyond standard invoice payment status.  
* Country-specific tax filing for subscription sales tax or VAT in the first release unless required by launch region.  
* AI-generated custom pricing contracts. Enterprise contracts can be managed manually in MVP.

## **2.3 Success Metrics**

| Metric | Target |
| :---- | :---- |
| Plan setup time | Super Admin can create a new plan with modules, limits and prices within 15 minutes. |
| Upgrade completion | At least 80% of company upgrades complete without support involvement. |
| Billing accuracy | No known high-severity billing defects in monthly invoice generation. |
| Limit transparency | Company admins can view employee/user usage and projected overage before checkout. |
| Trial conversion visibility | Sales/Admin can track trial status, remaining days, conversion and drop-off reasons. |
| Entitlement enforcement | 100% of gated modules and APIs check active entitlement and role permission. |

# **3\. Market and Product Research Summary**

Subscription systems in modern SaaS products generally combine a fixed plan fee with seat-based, quantity-based or usage-based billing. Public billing documentation from major billing infrastructure providers describes flat-rate plans, per-seat pricing, tiered pricing and usage-based pricing as standard recurring pricing models. Payroll/accounting products commonly use a base subscription plus a per-employee or per-person monthly charge. Balanzify should use this pattern but keep plan structure dynamic inside its own Super Admin panel.

| Pattern | R\&D Finding | Balanzify Decision |
| :---- | :---- | :---- |
| Plan base fee | A fixed monthly or annual price for a package of modules and included capacity. | Balanzify can define Starter, Growth, Scale and Enterprise plans with configurable base price. |
| Included capacity | Plans include employee count, user count, company/branch count, storage, payroll runs or transaction volume. | Starter example: 1-25 employees, up to 10 users, $150/month. |
| Overage/add-on | Additional usage beyond included limits can be charged per employee, per user, per payroll run, per company, per branch or per GB. | Employee overage example: each employee over 25 costs $6/month. |
| Annual discount | Annual billing can reduce effective monthly price while collecting upfront payment. | Admin can configure 10%, 15%, 20% or custom annual discount per plan. |
| Trial and promo | Trials, coupons, promotions and credits help conversion and retention. | Admin can create 14-day free trial, first-month discount, referral credit or sales-assisted offer. |
| Entitlement gating | Billing alone is not enough; application access must be driven by active subscription entitlements. | Subscription engine feeds module/menu/feature visibility and API authorization. |

Design principle: the pricing page shown to customers should be simple, while the admin configuration system behind it should be highly flexible.

# **4\. Product Scope**

| Scope Area | Description |
| :---- | :---- |
| Plan Catalog | Create and manage plan names, descriptions, billing periods, prices, included limits, add-on prices, trial eligibility and public/private visibility. |
| Module and Feature Packaging | Assign accounting, payroll, HR, inventory, report, tax, AI and support features to each plan. |
| Limit and Usage Engine | Track employee count, user count, branches, companies, storage, transaction volume, payroll runs and add-on usage. |
| Billing Engine | Calculate base fee, add-ons, overages, coupons, taxes, credits, proration and invoice totals. |
| Company Subscription Portal | Allow company owners/admins to view current plan, usage, invoices, payment status, upgrade/downgrade and buy add-ons. |
| Coupons and Promotions | Manage codes, automatic offers, plan eligibility, duration, redemption limits and discount stacking rules. |
| Referral System | Generate referral links/codes, track referred tenants and issue credits after successful paid conversion. |
| Trial System | Configure card-required or no-card trial, trial duration, extension, reminders and automatic conversion rules. |
| Lifecycle Management | Support new subscription, upgrade, downgrade, renewal, cancellation, reactivation, failed payment, grace and suspension states. |
| Reports and Audit | Provide MRR, ARR, churn, trial conversion, coupon usage, plan usage, overage revenue, failed payments and audit logs. |

# **5\. Personas and Permissions**

| Persona | Who | Access/Responsibility |
| :---- | :---- | :---- |
| Super Admin | Balanzify internal admin | Create plans, manage pricing, modules, coupons, trials, referrals, payment settings, global subscription reports and tenant overrides. |
| Billing Admin | Balanzify finance/support user | View invoices, payments, refunds, failed payments, credits, dunning events and subscription history. |
| Sales Admin | Balanzify sales team | Create sales-assisted offers, apply coupon/discount within permission limits, extend trials and view lead-to-subscription progress. |
| Company Owner | Tenant owner/customer | Subscribe, upgrade, downgrade, buy add-ons, update payment method, download invoices and manage cancellation. |
| Company Admin | Tenant admin | View subscription usage, receive warnings and request upgrade, subject to owner approval if configured. |
| Manager/Employee | Tenant users | Only see modules and features available under subscription and their role permissions. |
| Developer/API Client | Integration actor | Can query plan/entitlement status through secure internal APIs; cannot bypass entitlement checks. |

# **6\. Subscription Concepts and Terminology**

| Term | Definition |
| :---- | :---- |
| Tenant / Company | A customer account using Balanzify. One tenant can have one active subscription at a time in MVP. |
| Plan | A sellable package such as Starter, Growth or Enterprise. A plan contains modules, features, limits and pricing rules. |
| Plan Version | A locked version of a plan. Existing customers keep their version unless migrated to a new version. |
| Module | Large functional area such as Accounting, Sales, Expenses, Inventory, HRIS, Payroll, Reports, Tax Center or AI Assistant. |
| Feature | A specific capability inside a module such as invoices, purchase orders, payroll tax filing, bulk import or advanced reports. |
| Entitlement | The active permission to use a module, feature, API operation or limit based on subscription state. |
| Included Limit | Quantity included in the base plan price, such as 25 employees or 10 users. |
| Overage | Usage above the included limit. Example: 30 active employees on a 25-employee plan creates 5 employee overages. |
| Add-on | Optional paid extension such as extra employee capacity, extra users, premium support, tax filing, AI credits or extra storage. |
| Coupon | A discount code manually entered by a customer or applied by admin. |
| Offer | A campaign or automatic discount shown to eligible customers, often time-bound. |
| Referral Credit | Credit earned when an existing customer refers a new paying company. |
| Billing Cycle | Monthly or annual period for recurring subscription charge. |
| Proration | Partial-cycle charge or credit when subscription quantity/plan changes before the billing cycle ends. |
| Dunning | Payment recovery workflow for failed payments. |

# **7\. Pricing Strategy and Plan Structure**

## **7.1 Plan Architecture**

Balanzify pricing should be constructed from four layers:

1. Base plan fee: fixed monthly/annual subscription charge.  
2. Included limits: employee, user, company, branch, storage, payroll run, transaction and API usage allowances.  
3. Add-ons and overages: additional charge for usage above included limits or optional premium features.  
4. Discounts and credits: coupons, offers, referral credits, annual discount and manual account credits.

## **7.2 Recommended Initial Pricing Matrix**

| Plan | Base Price | Included Employees | Included Users | Employee Overage | Target Segment |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Starter | $150/month | 1-25 | Up to 10 | $6/extra employee/month | Small companies starting with accounting \+ core payroll/HR. |
| Growth | $250/month | 26-100 | Up to 25 | $5/extra employee/month | Growing businesses needing inventory, automation, advanced reports and multi-branch control. |
| Scale | $450/month | 101-300 | Up to 75 | $4/extra employee/month | Larger SMBs needing advanced approval, audit, multi-state payroll and more support. |
| Enterprise | Custom | Custom | Custom | Custom | Large/multi-entity customers with negotiated contract, SLA, dedicated support and custom limits. |

This pricing matrix is a recommended starting configuration. The actual values must be editable by Super Admin and should be stored as versioned records. The Starter plan example follows the requested rule: $150/month for 1-25 employees and up to 10 users, then $6 per extra employee per month.

## **7.3 Plan Configuration Fields**

| Configuration Area | Fields |
| :---- | :---- |
| Plan Identity | Plan name, slug, public title, internal name, display order, badge text, plan color, description, short tagline. |
| Plan Visibility | Public, hidden, invitation-only, sales-assisted, deprecated, region-specific, currency-specific. |
| Billing Cycle | Monthly, annual, quarterly, custom contract. |
| Base Pricing | Monthly base price, annual base price, annual discount percent, setup fee, implementation fee. |
| Included Limits | Employee min/max, included users, companies, branches, storage, transactions, payroll runs, API calls, AI credits. |
| Overage Rules | Per extra employee, per extra user, per extra branch, per extra payroll run, per extra GB, per extra AI credit. |
| Module Access | Enabled modules and feature groups. |
| Feature Access | Specific enabled/disabled actions, screens, reports, exports and automation features. |
| Trial Rules | Trial availability, default days, card required, trial extension allowed, auto-convert allowed. |
| Discount Eligibility | Allowed coupon types, max discount, offer eligibility, referral stack behavior. |
| Support Level | Email support, chat support, phone support, response SLA, dedicated account manager. |
| Contract Rules | Cancellation policy, downgrade rules, renewal notice, payment terms, custom invoice terms. |
| Compliance Flags | Audit log retention, payroll tax support, data export availability, security feature requirements. |

# **8\. Core Billing Logic and Calculation Rules**

## **8.1 Primary Formula**

| Component | Rule |
| :---- | :---- |
| Base Monthly Price | Configured plan base price for monthly billing. |
| Employee Overage Quantity | max(0, billable\_employee\_count \- included\_employee\_limit). |
| Employee Overage Charge | employee\_overage\_quantity x employee\_overage\_unit\_price. |
| User Overage Quantity | max(0, billable\_user\_count \- included\_user\_limit), if user overage is enabled. |
| User Overage Charge | user\_overage\_quantity x user\_overage\_unit\_price. |
| Add-on Charges | Sum of selected add-on recurring charges and usage-based charges. |
| Discounts | Coupon amount, offer discount, referral credit and manual credit based on stacking rules. |
| Tax | Calculated on taxable subscription line items if tax configuration is enabled. |
| Invoice Total | base \+ overage \+ add-ons \- discounts \+ tax \- credits. |

## **8.2 Requested Starter Example**

| Item | Calculation |
| :---- | :---- |
| Plan | Starter |
| Base Price | $150/month |
| Included Employee Limit | 25 employees |
| Included User Limit | 10 users |
| Actual Active/Billable Employees | 30 employees |
| Extra Employees | 30 \- 25 \= 5 |
| Extra Employee Rate | $6 per employee/month |
| Overage Charge | 5 x $6 \= $30/month |
| Monthly Subscription Total | $150 \+ $30 \= $180/month |

## **8.3 Billing Quantity Definition**

* **Billable employee count:** By default, count Active employees, Active contractors if included in payroll/HR module, and employees paid in the current billing cycle. Terminated/inactive employees are excluded unless they were paid or active during the billable period.  
* **Billable user count:** Count active login users with access to the tenant. Suspended users are excluded. Invited but not activated users may be excluded until activation, configurable by admin.  
* **Branch/company count:** Count active business units using Balanzify operational modules.  
* **Payroll run count:** Count finalized payroll runs in the billing cycle. Draft payroll runs are excluded.  
* **Storage count:** Count uploaded documents and attachments after compression, with daily or monthly snapshot logic.  
* **AI credit count:** Count successful AI actions only; failed or canceled actions should not consume credits.

## **8.4 Proration Rules**

| Scenario | Rule |
| :---- | :---- |
| Upgrade mid-cycle | Charge prorated difference immediately or include it in the next invoice based on account setting. Entitlements update immediately after successful payment or approved credit terms. |
| Downgrade mid-cycle | Default: schedule downgrade for next renewal to avoid data access loss. Optional: immediate downgrade with credit balance if allowed by admin. |
| Add employees mid-cycle | Charge prorated overage for remaining days in current cycle when company exceeds included employee limit. |
| Remove employees mid-cycle | Do not refund employee overage by default unless billing policy allows credit for reduced quantity. Keep a monthly maximum snapshot if chosen. |
| Annual plan upgrade | Charge prorated difference for remaining annual term. |
| Annual plan downgrade | Schedule for next renewal unless a billing admin approves immediate downgrade/credit. |
| Coupon after subscription starts | Apply from next invoice by default. Admin can choose immediate invoice adjustment. |
| Failed upgrade payment | Do not grant upgraded entitlements until payment succeeds, except for approved manual terms or trial extension. |

## **8.5 Overage Charging Models**

| Model | Behavior |
| :---- | :---- |
| Hard Block | Do not allow company to exceed included limit until they upgrade or buy add-on capacity. Best for high-risk actions such as payroll finalization without payment method. |
| Soft Warning | Allow temporary overage with warning and projected invoice. Good for adding employees/users during growth. |
| Auto Overage Billing | Allow overage automatically if payment method is valid. Invoice line items show quantity and rate. |
| Manual Approval | Company admin requests extra capacity; Balanzify Sales/Billing approves custom add-on. |
| Grace Overage | Allow limited excess for a short period, then restrict creating new resources if unresolved. |

# **9\. Super Admin Panel Requirements**

## **9.1 Admin Navigation Structure**

| Admin Menu | Purpose |
| :---- | :---- |
| Subscription Dashboard | MRR/ARR, active subscriptions, trials, churn, failed payments, upgrades, downgrades, coupon usage, overage revenue. |
| Plans | Create and manage plan catalog, plan versions, display order, pricing, visibility and module/feature matrix. |
| Modules & Features | Maintain feature catalogue and map features to module/menu/API permissions. |
| Limits & Usage Metrics | Define billable metrics, counters, included limits, overage rules and enforcement method. |
| Add-ons | Create recurring and one-time add-ons such as extra employees, extra users, premium support, tax filing and AI credits. |
| Coupons & Offers | Create coupon codes, automatic offers, eligibility rules, duration, stacking and redemption limits. |
| Referral Program | Create referral rewards, conversion rules, anti-abuse rules and credit issuance. |
| Trials | Default trial rules, trial extensions, card requirement, trial reminders and conversion settings. |
| Tenant Subscriptions | Search companies, view current plan, usage, invoices, payments, overrides, account status and billing history. |
| Invoices & Payments | Invoice list, payment attempts, failed payments, refunds, credits and dunning workflow. |
| Audit Logs | Track all subscription-related changes and access control changes. |

## **9.2 Plan Builder Wizard**

5. Basic details: name, tagline, description, badge, color, display order, visibility and target segment.  
6. Pricing: monthly price, annual price, setup fee, implementation fee, annual discount, currency and tax category.  
7. Limits: employee/user/company/branch/storage/API/payroll/AI limits and overage behavior.  
8. Modules and features: select modules, menus, actions, reports and integrations included in the plan.  
9. Add-ons: link available add-ons and define which add-ons are mandatory, optional or unavailable.  
10. Trial and promotions: define trial eligibility, allowed coupons/offers/referrals and discount stack rules.  
11. Review and publish: preview pricing page card, entitlement summary, billing calculation examples and plan version.

## **9.3 Feature Matrix Editor**

| Module | Feature Examples | Plan Control Type |
| :---- | :---- | :---- |
| Accounting Core | COA, journal, bank transactions, reconciliation, bank deposit | Enabled/disabled \+ transaction limits |
| Sales | Estimate, invoice, sales receipt, receive payment, credit memo, refund receipt | Enabled/disabled \+ monthly transaction cap |
| Expense | Bill, expense, cheque, purchase order, supplier credit, pay bills | Feature flags \+ plan tier restriction |
| Inventory | Inventory items, bundles, stock adjustment, low stock alerts, warehouse | Module entitlement \+ warehouse/add-on limits |
| Taxes & Agencies | Agencies, custom tax rates, reports, payroll tax center | Feature flags \+ compliance add-on |
| HRIS | Employee profiles, onboarding, documents, departments, designations | Employee limit \+ feature flags |
| Attendance & Leave | Shift, holiday, leave balance, leave application, encashment | Feature flags \+ employee limit |
| Payroll | Pay schedule, payroll process, payslip, deductions, direct deposit, tax calculation | Payroll add-on \+ per employee billing |
| Reports | Balance sheet, trial balance, P\&L, cash flow, AR/AP, payroll reports | Basic/advanced/custom report access |
| AI Assistant | Insights, anomaly detection, categorization, report summaries | Credit limit \+ add-on pricing |
| Support | Email, chat, priority support, onboarding assistance | Plan tier \+ support add-on |

# **10\. Company Self-Service Requirements**

| Feature | Requirement |
| :---- | :---- |
| Current Plan Overview | Show plan name, billing cycle, renewal date, invoice amount, payment status, trial days remaining and cancellation status. |
| Usage Monitor | Show active employee count, user count, branch count, payroll usage, storage and other plan limits with progress bars. |
| Plan Comparison | Allow company owner to compare current plan with upgrade/downgrade options and included modules/features. |
| Billing Preview | Before changing plan or adding employees, show line-by-line preview: base price, overages, add-ons, discounts, tax and prorated total. |
| Upgrade Flow | Upgrade plan immediately after payment or approved manual terms, update entitlements and send confirmation. |
| Downgrade Flow | Warn about unavailable modules/features and over-limit usage; schedule downgrade for next renewal by default. |
| Buy Add-on | Allow extra employee/user/storage/AI/support add-ons where plan allows. |
| Coupon Entry | Allow valid coupon entry during checkout or in subscription settings when allowed by rules. |
| Referral Area | Show referral code/link, reward status and credits earned. |
| Invoice History | List invoices, statuses, amounts, payment methods, downloadable PDFs and receipts. |
| Payment Method | Add/update card or bank payment method, mark default payment method and show verification status. |
| Cancellation | Allow cancellation request with reason capture, retention offer and scheduled end date confirmation. |
| Reactivation | Allow canceled or suspended company to reactivate with payment and plan selection. |

# **11\. Module, Feature and Entitlement Management**

## **11.1 Entitlement Enforcement Layers**

| Layer | Requirement |
| :---- | :---- |
| UI Layer | Hide disabled modules, menus, buttons, reports and upgrade CTAs. UI should not be the only enforcement layer. |
| API Layer | Every protected endpoint must validate tenant subscription status, feature entitlement and user role permission. |
| Service Layer | Business services check usage limits before creating billable resources such as employees, users, branches, payroll runs or AI actions. |
| Job/Worker Layer | Scheduled jobs verify subscription status before sending payroll, generating reports, sending reminders or consuming AI credits. |
| Data Layer | Data remains stored even if a feature is disabled. Access can become read-only or hidden based on downgrade rules. |
| Cache Layer | Use entitlement cache for performance but invalidate it on subscription change, payment success, plan migration, role change and module update. |

## **11.2 Access Behavior by Subscription State**

| Subscription State | Access Behavior |
| :---- | :---- |
| Trialing | All trial-included features active until trial end. Show trial banner and conversion CTA. |
| Active | Full access to purchased entitlements. |
| Past Due | Grace period access with warning banner and restricted high-risk actions after configured days. |
| Grace | Limited access while payment recovery is in progress. Admin can still update payment method. |
| Suspended | Read-only or blocked access except billing, payment update, invoice download and support contact. |
| Canceled \- Active Until Period End | Access continues until paid period end, then moves to canceled/archived. |
| Canceled/Expired | No operational access except billing history, data export if allowed and reactivation flow. |
| Manual Hold | Admin-imposed restriction for compliance, abuse or contract issue. |

# **12\. Coupon, Offer, Referral and Trial System**

## **12.1 Coupon Types**

| Coupon Type | Behavior |
| :---- | :---- |
| Percentage Discount | Example: 20% off monthly base price for 3 months. |
| Fixed Amount Discount | Example: $50 off first invoice. |
| Free Month | Example: first month free after trial conversion. |
| Add-on Discount | Example: 50% off payroll add-on for 2 months. |
| Employee Overage Discount | Example: first 10 extra employees free for first billing cycle. |
| Annual Discount Coupon | Example: 25% off annual plan for eligible customers. |
| Manual Credit | Account credit applied by billing admin for compensation or sales agreement. |

## **12.2 Coupon and Offer Rules**

* Coupon code must support uppercase/lowercase normalization and unique code validation.  
* Admin can define start date, end date, maximum redemptions, per-customer redemption limit and minimum invoice amount.  
* Admin can restrict coupon by plan, billing cycle, country, currency, industry, customer segment or sales owner.  
* Stacking rules must define whether coupon can combine with annual discount, referral credit, manual credit or another offer.  
* Coupon should be previewed before applying, showing discount impact on base, add-on, overage and tax lines.  
* Offer can be automatic without coupon code and only shown to eligible customers.  
* All coupon application, removal and override actions must be logged.

## **12.3 Referral Program Rules**

| Rule | Requirement |
| :---- | :---- |
| Referral Code/Link | Every eligible customer can copy a unique referral link or code. |
| Reward Trigger | Reward is issued only after referred company becomes paid and first invoice is successfully collected. |
| Reward Type | Account credit, fixed discount, free month, add-on credit or sales-defined custom reward. |
| Referrer Limit | Admin can set maximum monthly or lifetime rewards per referrer. |
| Anti-Abuse | Block self-referral, duplicate company referral, same payment method abuse and suspicious repeated signups. |
| Reward Visibility | Company owner can see pending, approved, rejected and redeemed referral rewards. |
| Accounting | Referral credit must appear as credit line on invoice or account balance adjustment. |

## **12.4 Free Trial Rules**

| Trial Rule | Requirement |
| :---- | :---- |
| Trial Duration | Default 14 days, configurable per plan or offer. |
| Card Required | Optional. Admin can choose no-card trial for low friction or card-required trial for higher intent. |
| Trial Feature Set | Trial can use full plan features or limited trial feature set. |
| Trial Extension | Sales/Admin can extend trial with reason and max extension policy. |
| Trial Reminder | Send reminders at configurable days: trial start, 7 days left, 3 days left, 1 day left, trial ended. |
| Trial Conversion | Convert to paid plan after payment method confirmation or manual approval. |
| Trial Expiry | If not converted, restrict to billing/subscription area and allow data export/reactivation if configured. |
| Trial Abuse Prevention | Limit one trial per company domain, phone, payment method or owner account unless admin overrides. |

# **13\. Upgrade, Downgrade, Cancellation and Renewal Workflows**

## **13.1 Upgrade Workflow**

12. Company owner opens Subscription \> Plans.  
13. System loads current plan, current usage and available upgrade options.  
14. Owner selects new plan or add-on.  
15. System shows billing preview including prorated charge, current credit, new renewal amount and enabled features.  
16. Owner confirms payment or chooses existing payment method.  
17. Payment succeeds or manual terms are approved.  
18. Subscription version updates, entitlement cache refreshes and new modules/features unlock immediately.  
19. System sends confirmation email/in-app notification and creates audit log.

## **13.2 Downgrade Workflow**

20. Company owner selects a lower plan.  
21. System compares current usage and current features against target plan.  
22. If usage exceeds target limits, show blocking items such as employees, users, branches or features above the lower plan limit.  
23. If target plan disables existing modules, show what becomes read-only, hidden or unavailable.  
24. Default action schedules downgrade for next renewal date.  
25. Immediate downgrade is only allowed when account is within target limits and admin policy allows immediate credit/downgrade.  
26. System sends scheduled downgrade confirmation and creates audit log.

## **13.3 Cancellation Workflow**

* Capture cancellation reason: too expensive, missing feature, switching provider, temporary pause, business closed, support issue or other.  
* Show retention offer only if eligible and not abusive.  
* By default, subscription remains active until paid period end.  
* After cancellation effective date, company enters canceled state with restricted access and data retention rules.  
* Owner can reactivate from cancellation page if allowed.

## **13.4 Renewal Workflow**

* Generate renewal invoice before or on renewal date depending on billing provider mode.  
* Calculate usage snapshot, overage, add-ons, coupons, referral credits and taxes.  
* Attempt payment using default payment method.  
* If payment succeeds, mark invoice paid and keep subscription active.  
* If payment fails, start dunning and grace period workflow.  
* Send invoice, receipt or failed payment notifications to billing contacts.

# **14\. Functional Requirements**

| ID | Area | Requirement | Priority |
| :---- | :---- | :---- | :---- |
| SUB-001 | Plan Catalog | Super Admin can create, edit, archive and clone plans. | Must Have |
| SUB-002 | Plan Versioning | Published plan changes create new version; existing subscriptions keep assigned version until migrated. | Must Have |
| SUB-003 | Pricing | Admin can configure monthly and annual prices, setup fees, overage rates and add-ons. | Must Have |
| SUB-004 | Limits | Admin can configure employee, user, branch, company, storage, API, payroll and AI credit limits. | Must Have |
| SUB-005 | Overage Billing | System calculates extra employee charge when count exceeds included employee limit. | Must Have |
| SUB-006 | Starter Example | Starter plan supports $150/month, 1-25 employees, up to 10 users, $6 per extra employee/month. | Must Have |
| SUB-007 | Feature Gating | Feature access is controlled by subscription entitlements and role permissions. | Must Have |
| SUB-008 | Subscription States | System supports trialing, active, past\_due, grace, suspended, canceled and expired states. | Must Have |
| SUB-009 | Checkout | Company owner can subscribe, upgrade or buy add-on with billing preview. | Must Have |
| SUB-010 | Downgrade Guardrail | System blocks or schedules downgrade if current usage/features exceed target plan. | Must Have |
| SUB-011 | Coupon System | Admin can create coupons with eligibility, duration, max redemption and stacking rules. | Must Have |
| SUB-012 | Offer System | Admin can create automatic offers for eligible customers. | Should Have |
| SUB-013 | Referral System | Customers can refer companies and earn credit after paid conversion. | Should Have |
| SUB-014 | Trial Management | Admin can configure trial duration, card requirement and extensions. | Must Have |
| SUB-015 | Invoice History | Company can view invoices, payment status and receipts. | Must Have |
| SUB-016 | Usage Monitor | Company can view usage against limits and projected overage. | Must Have |
| SUB-017 | Admin Overrides | Authorized admin can apply manual credits, plan override, trial extension and custom pricing. | Should Have |
| SUB-018 | Audit Logs | All subscription changes, pricing updates, coupon use and entitlement changes are logged. | Must Have |
| SUB-019 | Reports | Admin can view subscription analytics including MRR, ARR, churn, trial conversion and overage revenue. | Should Have |
| SUB-020 | Payment Failure | System supports dunning, grace period and suspension rules. | Must Have |
| SUB-021 | Entitlement Cache | System caches entitlements but invalidates immediately on subscription or role changes. | Must Have |
| SUB-022 | Migration | Admin can migrate tenants from old plan version to new plan version with preview. | Should Have |
| SUB-023 | Public Pricing Page | Public pricing page reads plan data from published plan catalog. | Should Have |
| SUB-024 | Multi-Currency | Admin can configure prices by currency/region when needed. | Could Have |
| SUB-025 | Payment Provider Integration | System can integrate with external billing/payment provider through webhooks and idempotent events. | Must Have |

# **15\. User Stories and Acceptance Criteria**

| Story ID | User Story | Acceptance Criteria |
| :---- | :---- | :---- |
| US-001 | As a Super Admin, I want to create a subscription plan with price, employee limit, user limit, modules and add-ons so that Balanzify can launch new packages without code changes. | Given I enter all required plan fields, when I publish the plan, then the plan appears in the admin plan list and can be displayed on pricing page if public. |
| US-002 | As a Super Admin, I want to set Starter at $150/month for 1-25 employees and up to 10 users with $6 per extra employee so that companies can scale beyond the included employee limit. | Given a company has 30 billable employees on Starter, when the billing preview runs, then it shows 5 extra employees, $30 overage and $180 total before tax/discount. |
| US-003 | As a Company Owner, I want to see my current employee/user usage against plan limits so that I understand whether I need to upgrade or pay overage. | Given I open Subscription Overview, when my employee count exceeds the included limit, then the page displays overage quantity, unit price and projected invoice impact. |
| US-004 | As a Company Owner, I want to upgrade my plan with a clear price preview so that I can unlock features immediately without hidden charges. | Given payment succeeds, when I confirm upgrade, then the system updates subscription, unlocks entitlements and sends confirmation. |
| US-005 | As a Company Owner, I want to downgrade my plan safely so that I do not lose data unexpectedly. | Given target plan has lower limits, when usage exceeds target limits, then the system shows blocking reasons and schedules or blocks downgrade according to policy. |
| US-006 | As a Sales Admin, I want to create an offer or coupon for a selected customer segment so that I can improve trial conversion. | Given I create a coupon with validity and redemption rules, when an eligible customer applies it, then discount appears in billing preview and invoice. |
| US-007 | As a Company Owner, I want a referral code so that I can invite another business and receive a credit after they become paid. | Given the referred tenant pays the first invoice, when the referral is validated, then credit is added to the referrer account. |
| US-008 | As a Support Agent, I want to see subscription history and failed payment events so that I can troubleshoot customer access problems. | Given I open tenant subscription timeline, when events exist, then I can view plan changes, payments, dunning actions, coupons and admin overrides. |
| US-009 | As a Developer, I want a central entitlement API so that every module can check access consistently. | Given a user calls a gated endpoint, when the entitlement is missing or subscription is inactive, then the API returns a consistent access denied response with upgrade metadata. |
| US-010 | As a Billing Admin, I want to generate subscription reports so that I can track revenue, churn, trial conversion and overage revenue. | Given report filters are selected, when I run the report, then the system shows accurate subscription metrics and export options. |


# **16\. UX and Screen Requirements**

| Screen | Core UX Requirements |
| :---- | :---- |
| Public Pricing Page | Employee slider, monthly/annual toggle, plan cards, included employee/user limits, add-on preview, popular badge, free trial CTA, plan comparison. |
| Plan Builder | Step-by-step admin wizard, live card preview, module/feature checklist, pricing simulator, publish/unpublish and versioning. |
| Feature Matrix | Grid with plan columns and feature rows, bulk enable/disable, search, module filters and export. |
| Usage Dashboard | Progress bars for employees/users/storage/payroll/AI credits, warnings, projected overage and upgrade CTA. |
| Billing Preview Drawer | Before checkout/change: base price, overages, add-ons, discounts, taxes, credit, proration and total due. |
| Checkout/Payment | Selected plan, billing cycle, coupon field, payment method, billing details, terms acceptance and confirmation. |
| Subscription Detail \- Company | Current plan, billing cycle, renewal date, payment method, invoices, usage, add-ons and lifecycle actions. |
| Subscription Detail \- Admin | Tenant details, plan version, usage, invoice timeline, payment events, coupon/referral data, overrides and audit log. |
| Coupon/Offer Builder | Discount type, value, validity, eligibility, stack rules, redemption limits and preview. |
| Referral Dashboard | Referral link/code, pending/approved rewards, referred companies and credit history. |
| Trial Dashboard | Trial companies, days remaining, conversion status, extension action and outreach notes. |
| Dunning/Failed Payment | Failed payment timeline, retry schedule, grace deadline, communication log and manual resolution action. |

Pricing page UI direction: support employee quantity slider and monthly/annual toggle. The value shown on the plan card should update immediately when employees change, including included limits and overage charge.

# **17\. Data Model**

| Entity | Key Fields | Purpose |
| :---- | :---- | :---- |
| tenants | id, name, owner\_user\_id, status, billing\_email, currency, country, timezone | Customer/company record. |
| modules | id, code, name, description, is\_active, display\_order | High-level product modules. |
| features | id, module\_id, code, name, type, api\_scope, menu\_key, is\_billable | Feature catalogue for gating. |
| plans | id, name, slug, status, visibility, display\_order, target\_segment | Plan identity record. |
| plan\_versions | id, plan\_id, version\_no, status, published\_at, effective\_from, effective\_to | Immutable pricing/entitlement version. |
| plan\_prices | id, plan\_version\_id, currency, billing\_cycle, base\_price, annual\_discount\_percent, setup\_fee | Price by billing cycle/currency. |
| plan\_limits | id, plan\_version\_id, metric\_code, included\_quantity, min\_quantity, max\_quantity, enforcement\_mode | Included usage limits. |
| plan\_features | id, plan\_version\_id, feature\_id, access\_level, limit\_value, metadata | Feature entitlement mapping. |
| add\_ons | id, code, name, pricing\_model, unit\_price, billing\_cycle, status | Optional/overage add-on definitions. |
| plan\_add\_ons | id, plan\_version\_id, add\_on\_id, availability, required\_flag | Add-ons available for each plan. |
| subscriptions | id, tenant\_id, plan\_version\_id, status, billing\_cycle, start\_date, current\_period\_start, current\_period\_end | Tenant subscription. |
| subscription\_items | id, subscription\_id, item\_type, item\_code, quantity, unit\_price, billing\_behavior | Plan/add-on/overage line items. |
| usage\_counters | id, tenant\_id, metric\_code, period\_start, period\_end, quantity, snapshot\_type | Measured usage for billing and limits. |
| invoices | id, tenant\_id, subscription\_id, invoice\_no, status, subtotal, discount, tax, total, due\_date | Subscription invoices. |
| invoice\_lines | id, invoice\_id, line\_type, description, quantity, unit\_price, amount, tax\_category | Invoice line breakdown. |
| payments | id, invoice\_id, provider, provider\_payment\_id, status, amount, paid\_at, failure\_reason | Payment attempts and results. |
| coupons | id, code, discount\_type, discount\_value, duration, start\_at, end\_at, max\_redemptions, status | Coupon definition. |
| coupon\_redemptions | id, coupon\_id, tenant\_id, subscription\_id, redeemed\_at, status | Coupon usage tracking. |
| offers | id, name, offer\_type, eligibility\_rule\_json, discount\_rule\_json, status | Automatic or admin-applied offers. |
| referrals | id, referrer\_tenant\_id, referred\_tenant\_id, code, status, reward\_type, reward\_value | Referral tracking. |
| credits | id, tenant\_id, source\_type, amount, remaining\_amount, expires\_at, status | Account credit ledger. |
| entitlement\_cache | tenant\_id, feature\_code, access\_level, limits\_json, expires\_at, source\_version | Fast entitlement lookup. |
| subscription\_events | id, tenant\_id, subscription\_id, event\_type, payload\_json, created\_by, created\_at | Timeline and audit event store. |
| audit\_logs | id, actor\_id, tenant\_id, action, old\_value\_json, new\_value\_json, ip\_address, created\_at | Compliance audit log. |

# **18\. API Requirements**

| Endpoint | Purpose | Access |
| :---- | :---- | :---- |
| GET /admin/subscription/plans | List all plans and versions. | Super Admin/Billing Admin |
| POST /admin/subscription/plans | Create draft plan. | Super Admin |
| PATCH /admin/subscription/plans/{id} | Update draft plan metadata. | Super Admin |
| POST /admin/subscription/plans/{id}/publish | Publish plan version. | Super Admin |
| POST /admin/subscription/plans/{id}/clone | Clone plan for new version. | Super Admin |
| GET /admin/subscription/features | List modules and feature catalogue. | Super Admin |
| POST /admin/subscription/coupons | Create coupon. | Super Admin/Sales Admin |
| GET /company/subscription/current | Get current company plan, usage, invoice and actions. | Company Owner/Admin |
| GET /company/subscription/plans | List available plans for company. | Company Owner/Admin |
| POST /company/subscription/preview | Preview upgrade/downgrade/add-on/coupon calculation. | Company Owner/Admin |
| POST /company/subscription/checkout | Create checkout session or payment intent for plan change. | Company Owner |
| POST /company/subscription/change-plan | Apply plan change after payment/approval. | Company Owner |
| POST /company/subscription/cancel | Request cancellation. | Company Owner |
| POST /company/subscription/reactivate | Reactivate canceled/suspended subscription. | Company Owner |
| GET /company/subscription/invoices | List invoices and payment history. | Company Owner/Admin |
| POST /internal/entitlements/check | Check entitlement for module/feature/action. | Internal services |
| POST /internal/usage/track | Track usage event or update counter. | Internal services |
| POST /webhooks/billing-provider | Receive payment provider events idempotently. | System |

## **18.1 Billing Preview Response Example**

Example response for Starter plan with 30 employees:

{  
  "plan": "Starter",  
  "billing\_cycle": "monthly",  
  "base\_price": 150.00,  
  "included\_employees": 25,  
  "billable\_employees": 30,  
  "employee\_overage\_quantity": 5,  
  "employee\_overage\_unit\_price": 6.00,  
  "employee\_overage\_amount": 30.00,  
  "discount\_amount": 0.00,  
  "tax\_amount": 0.00,  
  "total\_due": 180.00  
}

# **19\. Event, Notification and Audit Requirements**

| Event | Trigger | Recipients |
| :---- | :---- | :---- |
| subscription.created | New subscription created. | Owner, Admin, Billing Admin |
| subscription.trial\_started | Trial started with end date. | Owner, Sales Admin |
| subscription.trial\_ending | Trial is ending soon. | Owner, Admin, Sales Admin |
| subscription.upgraded | Plan upgraded or add-on purchased. | Owner, Admin, Billing Admin |
| subscription.downgrade\_scheduled | Downgrade scheduled for next renewal. | Owner, Admin |
| subscription.canceled | Cancellation requested or effective. | Owner, Admin, Billing Admin |
| invoice.created | Invoice generated. | Billing contact |
| invoice.paid | Payment collected. | Billing contact, Billing Admin |
| invoice.payment\_failed | Payment failed; dunning begins. | Owner, billing contact, Support |
| usage.near\_limit | Usage reaches 80% or configurable threshold. | Company Admin/Owner |
| usage.over\_limit | Usage exceeds included limit. | Company Admin/Owner, Billing Admin |
| coupon.applied | Coupon applied to subscription/invoice. | Owner, Billing Admin |
| referral.reward\_approved | Referral reward approved. | Referrer owner |
| entitlement.changed | Feature entitlement changed due to plan update. | System audit only |

* Every subscription event must store actor, tenant, timestamp, old values, new values, source IP/user agent where available and correlation ID.  
* Payment webhooks must be idempotent. Replayed webhook events must not duplicate invoices, credits or entitlements.  
* Notifications should support email and in-app channels in MVP; Slack/SMS can be added later.

# **20\. Accounting, Invoice and Revenue Rules**

| Area | Rule |
| :---- | :---- |
| Invoice Line Clarity | Base subscription, employee overage, user overage, add-ons, discounts, credits and tax should appear as separate invoice lines. |
| Subscription Revenue Account | Base subscription and recurring add-on revenue should map to subscription income account. |
| Overage Revenue Account | Employee/user overage charges can map to subscription overage income for reporting. |
| Discounts | Discounts should reduce invoice revenue or appear as discount line according to accounting policy. |
| Credits | Referral/manual credits should reduce amount due and be tracked in credit ledger. |
| Failed Payment | Invoice remains open/past due until paid, voided or written off. |
| Refund | Refund creates a payment reversal/refund transaction and updates invoice/payment status according to provider response. |
| Tax | Tax line should be calculated per billing address and tax category when tax engine is enabled. |
| Audit | Any manual adjustment must require reason and be visible in invoice/subscription timeline. |

# **21\. Edge Cases and Guardrails**

| Case | Expected Behavior |
| :---- | :---- |
| Company adds 26th employee on Starter | Show overage preview: 1 extra x $6/month. If auto-overage enabled and payment method valid, allow activation and bill overage. If hard block, require upgrade/add-on purchase. |
| Company has 35 employees and tries to downgrade to Starter | Block or schedule downgrade; show that Starter includes 25 employees and requires reducing billable employees or accepting overage if allowed. |
| Coupon expires before invoice | Coupon should not apply to future invoice if expiration/duration has passed. Show clear invoice preview. |
| Coupon plus referral credit | Apply stacking rules. If not stackable, show which discount wins and why. |
| Payment succeeds but webhook is delayed | Use checkout confirmation and webhook reconciliation. Avoid duplicate entitlement activation. |
| Webhook replay | Use provider event ID and idempotency key to prevent duplicate payment/invoice updates. |
| Plan feature disabled after customer has data | Do not delete customer data. Convert to read-only, hide creation buttons or allow export based on policy. |
| Billing admin edits published plan | Require new plan version. Do not silently change existing customers. |
| Employee status changed after invoice generated | Use billing-period snapshot to avoid invoice fluctuation unless adjustment is issued. |
| Trial ends without payment method | Move to expired trial state with restricted access and conversion CTA. |
| Annual customer adds employees mid-year | Calculate prorated annual overage for remaining term or bill monthly add-on according to plan setting. |
| Owner cancels with unpaid invoices | Cancellation does not erase outstanding invoice. Access policy follows billing state and cancellation rules. |
| Manual override conflicts with payment provider | Internal subscription state must reconcile provider state and show warning if out of sync. |
| User role allows feature but subscription does not | Deny access and show upgrade message; subscription entitlement is required before role permission. |
| Subscription allows feature but role does not | Deny access and show permission message; role access is still required. |

# **22\. Non-Functional Requirements**

| Category | Requirement |
| :---- | :---- |
| Security | Payment data must not be stored directly unless PCI scope is handled. Use tokenized payment methods from provider. Sensitive billing settings require RBAC. |
| Availability | Entitlement check should not fail open. If billing provider is down, use cached entitlement state with short TTL and safe fallback. |
| Performance | Entitlement checks should respond under 50ms from cache for common paths. |
| Scalability | Usage counters must support large tenants and high-volume events through aggregation and periodic snapshots. |
| Auditability | All plan, price, entitlement, coupon, credit and subscription state changes must be logged. |
| Reliability | Webhook processing must be idempotent and retry-safe. |
| Data Integrity | Historical invoices and plan versions must remain immutable after finalization. |
| Access Control | Subscription gates and RBAC both apply. Higher subscription does not bypass user permissions. |
| Localization | Support configurable currency symbols, date formats and billing address formats. |
| Extensibility | Pricing engine should support future pricing models without rewriting checkout and entitlement logic. |
| Observability | Log subscription state transitions, webhook failures, preview calculations, invoice generation and entitlement denials. |
| Compliance | Maintain audit records for billing adjustments and access changes. Follow payment provider security guidance. |

# **23\. QA Test Plan**

| Test Area | Scenario | Expected Result |
| :---- | :---- | :---- |
| Plan Creation | Create Starter plan with $150 base, 25 employees, 10 users and $6 employee overage. | Plan publishes and appears in catalog with correct version. |
| Billing Preview | Preview Starter with 25 employees. | Total is $150 before tax/discount. |
| Overage Billing | Preview Starter with 30 employees. | Shows 5 extra employees x $6 \= $30; total $180. |
| User Limit Warning | Starter tenant reaches 10 users and invites 11th user. | Shows warning/block/overage based on configured enforcement. |
| Upgrade | Upgrade Starter to Growth mid-cycle. | Prorated difference calculated; entitlements update after payment. |
| Downgrade Block | Downgrade Growth tenant with 80 employees to Starter. | System blocks or schedules downgrade and lists over-limit employees. |
| Coupon Eligibility | Apply Starter-only coupon to Growth plan. | Coupon rejected with clear message. |
| Coupon Duration | Apply 20% off for 3 months. | Discount appears on first 3 eligible invoices only. |
| Referral Credit | Referred tenant pays first invoice. | Referrer gets credit and audit log. |
| Trial Expiry | Trial ends without payment method. | Tenant moves to expired trial/restricted state. |
| Payment Failure | Renewal payment fails. | Invoice past due, dunning notification sent, access follows grace rule. |
| Webhook Replay | Payment webhook received twice. | Payment is recorded once only. |
| Feature Gate UI | Tenant without Inventory opens inventory URL directly. | API denies access and UI shows upgrade message. |
| RBAC \+ Subscription | User has role permission but tenant lacks feature. | Access denied due to subscription entitlement. |
| Plan Versioning | Admin edits published plan price. | New draft/version created; existing subscribers unaffected. |
| Invoice Lines | Subscription has base \+ overage \+ coupon \+ referral credit. | Invoice shows separate line items with correct totals. |
| Audit Log | Admin applies manual credit. | Audit log stores actor, time, reason, old/new values. |
| Annual Plan Overage | Annual tenant adds 5 employees mid-year. | Prorated annual overage calculated based on remaining days. |
| Cancellation | Owner cancels monthly subscription. | Access remains until period end by default and reason is captured. |
| Reactivation | Canceled tenant reactivates and pays. | Subscription active and entitlements restored. |

# **24\. Implementation Roadmap**

| Phase | Deliverables | Estimate |
| :---- | :---- | :---- |
| Phase 1 \- Foundation | Plan catalog, plan versioning, module/feature catalogue, entitlement API, basic subscription states, admin plan builder. | 2-3 weeks |
| Phase 2 \- Billing MVP | Company subscription page, plan comparison, billing preview, base \+ employee overage formula, invoice line generation, checkout integration, payment webhooks. | 3-4 weeks |
| Phase 3 \- Limits and Add-ons | Usage counters, employee/user limit enforcement, overage billing, add-on builder, upgrade/downgrade guardrails and entitlement cache invalidation. | 3-4 weeks |
| Phase 4 \- Promotions | Coupon builder, automatic offers, trial system, referral system, account credits and discount stacking rules. | 2-3 weeks |
| Phase 5 \- Lifecycle and Reports | Dunning, cancellation, reactivation, invoice history, subscription analytics, MRR/ARR/churn reports and support timeline. | 2-3 weeks |
| Phase 6 \- Enterprise Hardening | Multi-currency, region-specific plans, contract plans, custom pricing overrides, SLA/support add-ons, advanced audit and migration tooling. | 3-5 weeks |

# **25\. Open Questions and Decisions**

| Question | Recommended Decision |
| :---- | :---- |
| Billable employee definition | Should inactive employees count if they were paid in the cycle? Recommended: count active employees plus employees paid in current billing cycle. |
| User overage pricing | Should Starter block after 10 users or charge extra users? Recommended: make enforcement configurable per plan. |
| Annual discount | What default annual discount should be shown? Recommended: configure per plan, e.g., 20% annual saving. |
| Payment provider | Which provider will handle checkout, cards, bank payments, invoices and subscription webhooks? Recommended: choose provider that supports recurring billing, coupons, proration and webhooks. |
| Trial card requirement | Should Starter trial require card? Recommended: no-card trial for marketing campaigns, card-required for sales-assisted demos if needed. |
| Downgrade timing | Should downgrade happen immediately or at renewal? Recommended: schedule at renewal by default. |
| Data access after cancellation | How long can canceled customers access/download data? Recommended: configurable retention policy. |
| Tax collection | Will Balanzify collect sales tax/VAT on SaaS subscription? Recommended: plan tax category and tax engine integration later if launch region requires it. |
| Custom enterprise contract | Will enterprise customers be billed outside payment provider? Recommended: support manual invoice and custom terms in Phase 6\. |
| Referral reward amount | What credit should be offered? Recommended: make dynamic per campaign, such as $50 account credit after first paid invoice. |

# **26\. References**

| Reference | URL / Source |
| :---- | :---- |
| Stripe Docs \- Recurring pricing models | https://docs.stripe.com/products-prices/pricing-models |
| Stripe Docs \- Subscription quantities and licensed usage | https://docs.stripe.com/billing/subscriptions/quantities |
| Stripe Billing \- Recurring payments and subscription billing | https://stripe.com/billing |
| QuickBooks Payroll pricing page | https://quickbooks.intuit.com/payroll/pricing/ |
| Gusto pricing page | https://gusto.com/product/pricing |
| Balanzify internal product documentation | Existing Balanzify accounting, payroll, HR, tax, report, inventory and module management documentation supplied in project context. |

All external references were used for product research patterns only. Final pricing, plan names and business rules should be controlled by Balanzify Super Admin configuration and approved internally before launch.

# **Appendix A \- Pricing Engine Pseudocode**

The following pseudocode expresses the core calculation for a monthly plan with employee overage. Engineering should convert it into tested backend service code and keep all values versioned.

function calculateInvoicePreview(planVersion, usage, addOns, discounts, billingContext) {  
  base \= planVersion.price\[billingContext.currency\]\[billingContext.cycle\].basePrice  
  employeeOverageQty \= max(0, usage.billableEmployees \- planVersion.limits.includedEmployees)  
  employeeOverageAmount \= employeeOverageQty \* planVersion.overages.employee.unitPrice  
  userOverageQty \= max(0, usage.billableUsers \- planVersion.limits.includedUsers)  
  userOverageAmount \= planVersion.overages.user.enabled  
    ? userOverageQty \* planVersion.overages.user.unitPrice  
    : 0  
  addOnAmount \= sum(addOns.map(item \=\> item.quantity \* item.unitPrice))  
  subtotal \= base \+ employeeOverageAmount \+ userOverageAmount \+ addOnAmount  
  discountAmount \= applyDiscountRules(discounts, subtotal, planVersion, billingContext)  
  taxableAmount \= max(0, subtotal \- discountAmount)  
  taxAmount \= calculateTax(taxableAmount, billingContext.taxProfile)  
  creditsApplied \= applyAccountCredits(taxableAmount \+ taxAmount, billingContext.credits)  
  totalDue \= taxableAmount \+ taxAmount \- creditsApplied  
  return lineItemBreakdown(base, employeeOverageQty, employeeOverageAmount,  
                           userOverageQty, userOverageAmount,  
                           addOnAmount, discountAmount, taxAmount,  
                           creditsApplied, totalDue)  
}

# **Appendix B \- Starter Plan Calculation Scenarios**

| Usage Scenario | Base | Extra Employees | Employee Overage | Monthly Total |
| :---- | :---- | :---- | :---- | :---- |
| 25 employees, 8 users | $150 | 0 | $0 | $150 |
| 26 employees, 8 users | $150 | 1 | $6 | $156 |
| 30 employees, 10 users | $150 | 5 | $30 | $180 |
| 40 employees, 10 users | $150 | 15 | $90 | $240 |
| 50 employees, 12 users | $150 | 25 | $150 | $300 before any user overage if user overage is enabled |

