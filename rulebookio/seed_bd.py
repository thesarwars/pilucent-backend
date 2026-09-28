"""Bangladesh rule sets, ported from the front end's `rules.js`.

Every value, confidence state, citation and note below is transcribed from
`Balanzify Bangladesh - complete/rules.js` (and its catalogue, which states the
confidence of the labour values the per-set objects leave untagged). Changes
from the source, all deliberate:

* Tax sets are stored with an effective window instead of an assessment-year
  key. The front end labels a set by the July-to-June year it is withheld in
  (`'2026-27'` is loaded on 2026-07-01 and used on 2027-03-08), so `2026-27`
  runs 2026-07-01 to 2027-06-30. `rules.js` defines no set for 2027-28 or
  2029-30; the rule book throws for those dates rather than guess.
* `employmentExemptionFraction` is the exact fraction `1/3` (doc §7.5,
  "lower of one third"), not the `0.3333` approximation, which understates the
  exemption by up to Tk 167 on a Tk 500,000 ceiling.
* Slab rows are `{width, rate}`. They are band widths, not cumulative
  thresholds -- the source called the field `upTo` and needed a note to say so.
* Minimum-wage grades are keyed `G1`..`G7`, the contract's grade enum
  (doc §2.2), instead of `GRADE_1`..`GRADE_7`.
* Rates are decimal strings, so no binary float reaches a statutory figure.
* A labour value the source tags neither per-value nor in its catalogue takes
  its set's confidence: DRAFTED for the 2015 set (`verified: false`, no state),
  CORROBORATED for the 2026 amendment (the set's own `confidence`).
"""

from copy import deepcopy
from datetime import date

DRAFTED, CORROBORATED, DISPUTED, VERIFIED = "DRAFTED", "CORROBORATED", "DISPUTED", "VERIFIED"

FA_2026 = "Finance Act 2026"
ITA = "Income Tax Act 2023"
BLA = "Bangladesh Labour Act 2006"


def r(value, confidence, citation=None, note=None):
    return {"value": value, "confidence": confidence, "citation": citation, "note": note}


def slabs(*rows):
    return [{"width": width, "rate": rate} for width, rate in rows]


ESTABLISHMENTS = [
    "FACTORY", "SHOP", "COMMERCIAL_ESTABLISHMENT", "INDUSTRIAL_ESTABLISHMENT",
    "ROAD_TRANSPORT", "TEA_PLANTATION", "NEWSPAPER",
]
TAXPAYER_CATEGORIES = [
    "GENERAL", "FEMALE", "SENIOR_CITIZEN_65_PLUS", "PERSON_WITH_DISABILITY",
    "THIRD_GENDER", "WAR_WOUNDED_FREEDOM_FIGHTER", "NON_RESIDENT_FOREIGN",
]
WORKER_CATEGORIES = ["PROBATIONER", "PERMANENT", "TEMPORARY", "CASUAL", "SEASONAL", "APPRENTICE", "BADLI"]
SEPARATION_TYPES = ["TERMINATION", "RETRENCHMENT", "DISCHARGE", "DISMISSAL", "RESIGNATION", "RETIREMENT", "DEATH"]


# --------------------------------------------------------------------- income tax

TAX_2026_27 = {
    "taxFreeThresholds": {
        "GENERAL": r(400000, VERIFIED, FA_2026, "Raised from 375,000. Parliament amended the Bill upward at passage — sources dated before 29 Jun 2026 show the superseded figure."),
        "FEMALE": r(450000, VERIFIED, FA_2026, "RB-TAX correction — the prototype held null, so a woman could not be computed at all."),
        "SENIOR_CITIZEN_65_PLUS": r(450000, VERIFIED, FA_2026, "RB-TAX correction — same as the female threshold."),
        "PERSON_WITH_DISABILITY": r(525000, VERIFIED, FA_2026, "RB-TAX correction."),
        "THIRD_GENDER": r(525000, VERIFIED, FA_2026, "RB-TAX correction."),
        "WAR_WOUNDED_FREEDOM_FIGHTER": r(550000, VERIFIED, FA_2026, "RB-TAX correction. Now includes gazetted July 2024 fighters."),
        "NON_RESIDENT_FOREIGN": r(0, VERIFIED, ITA, "Flat 30% on Bangladesh-source income — the slab walk must be bypassed, not just the threshold zeroed."),
    },
    "disabledChildAddition": r(50000, VERIFIED, FA_2026, "Per disabled child, claimable by one parent or guardian only — the system must prevent both parents claiming."),
    "employmentExemptionFraction": r("1/3", VERIFIED, "Income Tax Act 2023, Sixth Sch. Pt 1, para 27"),
    "employmentExemptionCeiling": r(500000, VERIFIED, "Income Tax Act 2023, Sixth Sch. Pt 1, para 27", "Ceiling rose from 450,000 by the Finance Ordinance 2025. Whether 500,000 first bites in AY 2025-26 or 2026-27 is unconfirmed."),
    "nonResidentForeignFlatRate": r("0.30", VERIFIED, ITA, "Bypasses the slab walk entirely."),
    "slabs": r(
        slabs((300000, "0.10"), (400000, "0.15"), (500000, "0.20"), (2000000, "0.25"), (None, "0.30")),
        VERIFIED, "Finance Act 2026, Second Sch.",
        "Band widths, not thresholds. The 5% entry band was abolished — the entry rate doubled from 5% to 10%.",
    ),
    "rebateRateOnInvestment": r("0.10", VERIFIED, "Income Tax Act 2023, s.78"),
    "rebateRateOnTaxableIncome": r("0.03", VERIFIED, "Income Tax Act 2023, s.78"),
    "rebateCeiling": r(750000, VERIFIED, "Income Tax Act 2023, s.78", "Lowest of three legs. The 15% rate and the 1,000,000 ceiling are gone from AY 2026-27."),
    "rebateRecognisedPfOnly": r(True, CORROBORATED, FA_2026, "PF contributions qualify only if the fund is recognised. Premature withdrawal triggers pro-rated clawback."),
    "minimumTax": r(5000, VERIFIED, "Income Tax Act 2023, s.163", "Flat nationwide. The location bands were abolished from AY 2026-27 — do not build them."),
    "minimumTaxNewTaxpayer": r(1000, VERIFIED, "Income Tax Act 2023, s.163"),
    "perquisiteVehicleBands": r(
        [{"upToCc": 1500, "monthly": 15000}, {"upToCc": 2000, "monthly": 20000},
         {"upToCc": 2500, "monthly": 30000}, {"upToCc": None, "monthly": 50000}],
        VERIFIED, ITA, "RB-TAX correction: the two-band 10,000 / 25,000 structure is superseded — every company-car employee was undertaxed.",
    ),
    "perquisiteCeilingPerEmployee": r(2500000, CORROBORATED, "Income Tax Act 2023, s.55", "Raised from 2,000,000. The excess is disallowed to the employer and stays taxable to the employee."),
    "employerRecognisedPfExempt": r(True, VERIFIED, "Sixth Sch. Pt 1, para 6", "RB-TAX correction — the engine added employer PF to taxable income in every case, correct only for an unrecognised fund."),
    "gratuityExemptionCeiling": r(25000000, CORROBORATED, "Sixth Sch. Pt 1, para 6", "From an approved gratuity fund."),
    "festivalBonusTaxable": r(True, VERIFIED, "Income Tax Act 2023, s.32", "No exemption. A frequent source of under-withholding in March and September."),
    "wppfExemption": r(None, DRAFTED, "Sixth Sch.", "Commonly cited at 50,000 historically; could not be confirmed for AY 2026-27. Do not code a figure."),
    "surchargeNetWealthBands": r(
        [{"above": 40000000, "rate": "0.10"}, {"above": 100000000, "rate": "0.20"},
         {"above": 200000000, "rate": "0.30"}, {"above": 500000000, "rate": "0.35"}],
        CORROBORATED, ITA, "The 10% band also bites on more than one motor car or a house over 8,000 sq ft, whatever the wealth. Absent from the prototype entirely.",
    ),
    # Legacy two-key shape the profile screen's three-value `vehicle` enum reads
    # (NONE / UPTO_2500 / ABOVE_2500), carrying the corrected figures.
    "perquisiteVehicleUpTo2500cc": r(30000, VERIFIED, ITA, "Superseded shape: use perquisiteVehicleBands."),
    "perquisiteVehicleAbove2500cc": r(50000, VERIFIED, ITA, "Superseded shape: use perquisiteVehicleBands."),
}

# The Finance Act 2026 legislated a multi-year card through AY 2030-31.
TAX_2028_29 = {
    "taxFreeThresholds": {
        "GENERAL": r(450000, CORROBORATED, FA_2026),
        "FEMALE": r(500000, DRAFTED, FA_2026, "Conformed uplift assumed; not separately sourced."),
        "SENIOR_CITIZEN_65_PLUS": r(500000, DRAFTED, FA_2026, "Conformed uplift assumed."),
        "PERSON_WITH_DISABILITY": r(575000, DRAFTED, FA_2026, "Conformed uplift assumed."),
        "THIRD_GENDER": r(575000, DRAFTED, FA_2026, "Conformed uplift assumed."),
        "WAR_WOUNDED_FREEDOM_FIGHTER": r(600000, DRAFTED, FA_2026, "Conformed uplift assumed."),
        "NON_RESIDENT_FOREIGN": r(0, CORROBORATED, ITA),
    },
    "disabledChildAddition": r(50000, DRAFTED, FA_2026),
    "employmentExemptionFraction": r("1/3", DRAFTED),
    "employmentExemptionCeiling": r(500000, DRAFTED),
    "nonResidentForeignFlatRate": r("0.30", DRAFTED, ITA),
    "slabs": r(
        slabs((300000, "0.10"), (400000, "0.15"), (500000, "0.20"), (2000000, "0.25"), (26350000, "0.30"), (None, "0.35")),
        CORROBORATED, FA_2026, "35% applies above total income of Tk 30,000,000. Same shape for AY 2029-30.",
    ),
    "rebateRateOnInvestment": r("0.10", DRAFTED, "Income Tax Act 2023, s.78"),
    "rebateRateOnTaxableIncome": r("0.03", DRAFTED, "Income Tax Act 2023, s.78"),
    "rebateCeiling": r(750000, DRAFTED, "Income Tax Act 2023, s.78"),
    "minimumTax": r(5000, DRAFTED, "Income Tax Act 2023, s.163"),
    "minimumTaxNewTaxpayer": r(1000, DRAFTED, "Income Tax Act 2023, s.163"),
    "perquisiteVehicleUpTo2500cc": r(30000, DRAFTED),
    "perquisiteVehicleAbove2500cc": r(50000, DRAFTED),
}

TAX_2030_31 = {
    "taxFreeThresholds": {
        "GENERAL": r(500000, CORROBORATED, FA_2026),
        "FEMALE": r(550000, DRAFTED, None, "Conformed uplift assumed."),
        "SENIOR_CITIZEN_65_PLUS": r(550000, DRAFTED, None, "Conformed uplift assumed."),
        "PERSON_WITH_DISABILITY": r(625000, DRAFTED, None, "Conformed uplift assumed."),
        "THIRD_GENDER": r(625000, DRAFTED, None, "Conformed uplift assumed."),
        "WAR_WOUNDED_FREEDOM_FIGHTER": r(650000, DRAFTED, None, "Conformed uplift assumed."),
        "NON_RESIDENT_FOREIGN": r(0, CORROBORATED, ITA),
    },
    "disabledChildAddition": r(50000, DRAFTED),
    "employmentExemptionFraction": r("1/3", DRAFTED),
    "employmentExemptionCeiling": r(500000, DRAFTED),
    "nonResidentForeignFlatRate": r("0.30", DRAFTED, ITA),
    "slabs": r(
        slabs((300000, "0.10"), (400000, "0.15"), (500000, "0.20"), (2000000, "0.25"), (26300000, "0.30"), (None, "0.35")),
        CORROBORATED, FA_2026, "35% again above Tk 30,000,000.",
    ),
    "rebateRateOnInvestment": r("0.10", DRAFTED),
    "rebateRateOnTaxableIncome": r("0.03", DRAFTED),
    "rebateCeiling": r(750000, DRAFTED),
    "minimumTax": r(5000, DRAFTED),
    "minimumTaxNewTaxpayer": r(1000, DRAFTED),
    "perquisiteVehicleUpTo2500cc": r(30000, DRAFTED),
    "perquisiteVehicleAbove2500cc": r(50000, DRAFTED),
}

# Retained for historic recomputation — a payslip from 2025-26 must reproduce to the paisa.
TAX_2025_26 = {
    "taxFreeThresholds": {
        "GENERAL": r(375000, DRAFTED),
        "FEMALE": r(425000, DRAFTED),
        "SENIOR_CITIZEN_65_PLUS": r(425000, DRAFTED),
        "PERSON_WITH_DISABILITY": r(500000, DRAFTED),
        "THIRD_GENDER": r(475000, DRAFTED),
        "WAR_WOUNDED_FREEDOM_FIGHTER": r(500000, DRAFTED),
        "NON_RESIDENT_FOREIGN": r(0, DRAFTED),
    },
    "disabledChildAddition": r(50000, DRAFTED),
    "employmentExemptionFraction": r("1/3", DRAFTED),
    "employmentExemptionCeiling": r(450000, DRAFTED),
    "nonResidentForeignFlatRate": r("0.30", DRAFTED),
    "slabs": r(
        slabs((100000, "0.05"), (400000, "0.10"), (500000, "0.15"), (500000, "0.20"), (2000000, "0.25"), (None, "0.30")),
        DRAFTED,
    ),
    "rebateRateOnInvestment": r("0.15", DRAFTED),
    "rebateRateOnTaxableIncome": r("0.03", DRAFTED),
    "rebateCeiling": r(1000000, DRAFTED),
    "minimumTax": r(5000, DRAFTED),
    "minimumTaxNewTaxpayer": r(1000, DRAFTED),
    "perquisiteVehicleUpTo2500cc": r(10000, DRAFTED),
    "perquisiteVehicleAbove2500cc": r(25000, DRAFTED),
}


# --------------------------------------------------------------------- labour law

LABOUR_2015_CITATIONS = {
    "classification": f"{BLA}, s.2(65)",
    "overtime": f"{BLA}, s.108",
    "encashment": "Bangladesh Labour Rules 2015, Rule 107",
    "maternity": f"{BLA}, s.46",
    "maternityBenefit": f"{BLA}, s.48",
    "dailyLimit": f"{BLA}, s.100 and s.102",
    "weeklyLimit": f"{BLA}, s.102",
    "earnedLeave": f"{BLA}, s.117",
    "casualLeave": f"{BLA}, s.115",
    "sickLeave": f"{BLA}, s.116",
    "festivalHoliday": f"{BLA}, s.118",
    "compensatory": f"{BLA}, s.103",
    "gratuity": f"{BLA}, s.2(10)",
    "compensation": f"{BLA}, s.20, s.22, s.23, s.26",
    "pf": f"{BLA}, s.264",
    "insurance": f"{BLA}, s.99",
    "wppf": f"{BLA}, s.232, s.234",
    "festivalBonus": "Bangladesh Labour Rules 2015, Rule 111(5)",
    "wagePayment": f"{BLA}, s.123",
    "certificateOfService": f"{BLA} · Form-13",
    "minimumWage": "Minimum Wages Board gazette",
    "proration": "Bangladesh Labour Rules 2015, Rule 111 · company service rules",
}


def _labour_2015():
    D = DRAFTED
    c = LABOUR_2015_CITATIONS
    grades = lambda values: {f"G{i}": v for i, v in enumerate(values, 1)}  # noqa: E731
    return {
        "earnedLeaveRatioByEstablishment": r(
            {"FACTORY": 18, "SHOP": 18, "COMMERCIAL_ESTABLISHMENT": 18, "INDUSTRIAL_ESTABLISHMENT": 18,
             "ROAD_TRANSPORT": 18, "TEA_PLANTATION": 22, "NEWSPAPER": 11}, D, c["earnedLeave"]),
        "accumulationCapByEstablishment": r(
            {"FACTORY": 40, "ROAD_TRANSPORT": 40, "TEA_PLANTATION": 40, "SHOP": 60,
             "COMMERCIAL_ESTABLISHMENT": 60, "INDUSTRIAL_ESTABLISHMENT": 60, "NEWSPAPER": 60},
            D, c["earnedLeave"],
            "DEF-04: the cap is not 40 for every type. Split seeded, unverified — confirm against the Bangla text of s.117. "
            "docs/employee-profile.md §7.4 states 40 for most and 60 for newspaper only; the two disagree.",
        ),
        "casualLeaveDays": r(10, D, c["casualLeave"]),
        "sickLeaveDays": r(14, D, c["sickLeave"]),
        "festivalHolidayDays": r(11, D, c["festivalHoliday"]),
        "earnedLeaveEligibilityMonths": r(12, D, c["earnedLeave"]),
        "encashmentMaxPercent": r(50, D, c["encashment"]),
        "encashmentPerYear": r(1, D, c["encashment"]),
        "encashmentFraction": r("0.5", D, c["encashment"]),
        "gradeWageFloors": r(
            grades([8200, 7700, 7400, 7100, 6950, 6700, 6700]), D, "Minimum Wages Board, RMG sector gazette, December 2023",
            "The MONTHLY BASIC component by grade, not the total wage. The 2023 restructure also reduced the grade count; "
            "check against the Bangla gazette before these gate a released payslip.",
        ),
        "gradeWageFloorDefault": r(6700, D, c["minimumWage"]),
        "gradeTotalWageFloors": r(
            grades([15035, 14150, 13550, 13050, 12800, 12500, 12500]), D, "Minimum Wages Board, RMG sector gazette, December 2023",
            "The total monthly wage floor, for the gross-level check. Grade 6 is the entry grade under the 2023 structure.",
        ),
        "gradeTotalWageFloorDefault": r(12500, D, c["minimumWage"]),
        "overtimeMultiplier": r(2, D, c["overtime"]),
        "standardMonthHours": r(208, D, c["overtime"]),
        "standardHoursPerDay": r(8, D, c["dailyLimit"]),
        "standardDaysPerMonth": r(26, D, c["proration"]),
        "standardWeeklyHours": r(48, D, c["weeklyLimit"]),
        "maxDailyHours": r(10, D, c["dailyLimit"]),
        "maxWeeklyHours": r(60, D, c["weeklyLimit"]),
        "annualAverageWeeklyHours": r(56, D, c["weeklyLimit"]),
        "restIntervalMinutesOver6h": r(60, D, c["dailyLimit"]),
        "restIntervalMinutesOver5h": r(30, D, c["dailyLimit"]),
        "maternityTotalWeeks": r(16, D, c["maternity"]),
        "maternityWeeksBefore": r(8, D, c["maternity"]),
        "maternityWeeksAfter": r(8, D, c["maternity"]),
        "maternityBenefitDays": r(112, D, c["maternityBenefit"]),
        "maternityMinimumServiceMonths": r(6, D, c["maternity"]),
        "maternityMaxSurvivingChildren": r(2, D, c["maternity"]),
        "maternityReferencePeriodMonths": r(3, D, c["maternityBenefit"]),
        "pfMinPercent": r(7, D, c["pf"]),
        "pfMaxPercent": r(8, D, c["pf"]),
        "pfEmployeeRate": r("0.08", D, c["pf"]),
        "pfEmployerRate": r("0.08", D, c["pf"]),
        "gratuityDaysStandard": r(30, D, c["gratuity"]),
        "gratuityDaysAfterBreakpoint": r(45, D, c["gratuity"]),
        "gratuityYearBreakpoint": r(10, D, c["gratuity"], "Boundary unverified: exactly 10 years attracts 30 days."),
        "gratuityFractionMonths": r(6, D, c["gratuity"], "A part-year above this many months counts as a full year."),
        "compensationDaysPerYearBySeparationType": {
            "TERMINATION": r({"days": 30, "higherOfGratuity": True}, D, f"{BLA}, s.26"),
            "RETRENCHMENT": r({"days": 30, "higherOfGratuity": True}, D, f"{BLA}, s.20"),
            "DISCHARGE": r({"days": 30, "higherOfGratuity": True}, D, f"{BLA}, s.22"),
            "DISMISSAL": r({"days": 0, "higherOfGratuity": False}, D, f"{BLA}, s.23"),
            "RESIGNATION": r({"days": 0, "higherOfGratuity": False}, D),
            "RETIREMENT": r({"days": 0, "higherOfGratuity": False}, D, f"{BLA}, s.28"),
            "DEATH": r({"days": 30, "higherOfGratuity": False}, D, f"{BLA}, s.19"),
        },
        "noticePeriodDaysByWorkerCategory": r(
            {"PERMANENT": 120, "TEMPORARY": 30, "PROBATIONER": 0, "CASUAL": 0, "SEASONAL": 0, "APPRENTICE": 0, "BADLI": 0},
            D, c["compensation"],
        ),
        "festivalBonusServiceMonths": r(12, D, c["festivalBonus"]),
        "festivalBonusesPerYear": r(2, D, c["festivalBonus"]),
        "festivalBonusCapMultiple": r(1, D, c["festivalBonus"]),
        "festivalBonusFloorEnforced": r(False, D, c["festivalBonus"]),
        "wppfRate": r("0.05", D, c["wppf"]),
        "wppfMinServiceDays": r(183, D, c["wppf"]),
        "wppfSplit": r({"PARTICIPATION": "0.8", "WELFARE": "0.1", "FOUNDATION": "0.1"}, D, c["wppf"]),
        "citations": dict(c),
    }


def _labour_2026():
    """Labour (Amendment) Act 2026 — Act 43 of 2026, effective 10 April 2026 —
    as a delta over the 2015 body, stored whole."""
    V, C, D, X = VERIFIED, CORROBORATED, DRAFTED, DISPUTED
    base = _labour_2015()
    out = {}
    # Values the amendment did not touch carry the amended set's confidence.
    for key, node in base.items():
        if key == "citations":
            continue
        if "confidence" in node:
            out[key] = dict(node, confidence=C)
        else:
            out[key] = {k: dict(v, confidence=C) for k, v in node.items()}
    citations = dict(base["citations"])
    citations.update({
        "maternity": f"{BLA}, s.46 as amended 2026",
        "layoff": f"{BLA}, s.16 as amended 2026",
        "resignation": f"{BLA}, s.27(4) as amended 2026",
        "dismissal": f"{BLA}, s.23 as amended 2026",
        "retirement": f"{BLA}, s.28",
        "death": f"{BLA}, s.19 as amended 2026",
        "continuousService": "Labour (Amendment) Act 2026",
        "complaintCommittee": f"{BLA}, s.332, s.332A",
        "safetyCommittee": f"{BLA}, s.90A",
        "unionCheckOff": f"{BLA}, s.204",
    })
    c = citations
    out.update({
        # Confidence stated by the catalogue for values carried from 2015.
        "casualLeaveDays": r(10, V, c["casualLeave"]),
        "sickLeaveDays": r(14, V, c["sickLeave"]),
        "earnedLeaveRatioByEstablishment": dict(base["earnedLeaveRatioByEstablishment"], confidence=C),
        "accumulationCapByEstablishment": dict(base["accumulationCapByEstablishment"], confidence=D),
        "gradeWageFloors": dict(base["gradeWageFloors"], confidence=D),
        "gradeTotalWageFloors": dict(base["gradeTotalWageFloors"], confidence=D),
        "overtimeMultiplier": r(2, V, c["overtime"]),
        "festivalBonusServiceMonths": r(12, C, c["festivalBonus"]),
        "festivalBonusesPerYear": r(2, C, c["festivalBonus"]),
        "maternityMinimumServiceMonths": r(6, V, f"{BLA}, s.46"),
        # RB-MAT — the highest-exposure change in the amendment.
        "maternityBenefitDays": r(120, V, c["maternity"], "Was 112 days."),
        "maternityTotalWeeks": r(17, V, c["maternity"]),
        "maternityDaysBefore": r(60, V, c["maternity"], "Was 8 + 8 weeks."),
        "maternityDaysAfter": r(60, V, c["maternity"]),
        "maternityBenefitBasis": r(
            "ACT_S48", X, f"{BLA}, s.48",
            "The 2022 Rules amendment computes on 1 month ÷ 26, which materially reduces the benefit. A rule cannot "
            "override its parent Act, so s.48 should prevail; practice appears to follow the Rules. The basis is an election.",
        ),
        "maternityBenefitBasisOptions": r(
            {"ACT_S48": {"label": "3 months' wages ÷ days actually worked", "citation": f"{BLA}, s.48"},
             "RULES_2022": {"label": "1 month's wages ÷ 26", "citation": "Bangladesh Labour Rules 2015 as amended 2022"}},
            X, f"{BLA}, s.48",
        ),
        "maternityPaymentWorkingDays": r(3, C, c["maternity"]),
        "maternityProofOfBirthMonths": r(3, C, c["maternity"]),
        "maternityEmploymentBanWeeks": r(8, C, c["maternity"]),
        "maternityDismissalProtection": r({"beforeMonths": 6, "afterWeeks": 8}, V, f"{BLA}, s.50"),
        "paternityLeaveDays": r(0, V, None, "No statutory paternity leave exists. A two-week recommendation in April 2025 was not enacted."),
        # RB-LEAVE
        "festivalHolidayDays": r(13, V, c["festivalHoliday"], "Raised from 11 by the 2026 amendment."),
        # RB-SEP — resignation, dismissal, retirement and death all now carry entitlements.
        "compensationDaysPerYearBySeparationType": {
            "TERMINATION": r({"days": 30, "higherOfGratuity": True}, V, f"{BLA}, s.26(4)"),
            "RETRENCHMENT": r({"days": 30, "higherOfGratuity": True}, V, f"{BLA}, s.20"),
            "DISCHARGE": r({"days": 30, "higherOfGratuity": True}, V, f"{BLA}, s.22"),
            "DISMISSAL": r(
                {"days": 15, "higherOfGratuity": False, "minimumServiceYears": 1}, X, f"{BLA}, s.23",
                "Nil where the misconduct is theft, fraud, dishonesty, rioting, arson or wilful breach of discipline. "
                "Sources split on whether 2026 creates this or extends it from removal to dismissal.",
            ),
            "RESIGNATION": r(
                {"graduated": True, "higherOfGratuity": True}, X, f"{BLA}, s.27(4)",
                "Five sources give three different band boundaries. Money paid to every leaver — the single "
                "highest-risk figure in the rule book. Resolve the band from resignationBenefitBands before use.",
            ),
            "RETIREMENT": r({"days": 30, "higherOfGratuity": True}, V, f"{BLA}, s.28"),
            "DEATH": r(
                {"days": 30, "daysAboveTenYears": 45, "higherOfGratuity": True}, V, f"{BLA}, s.19",
                "The prototype paid a flat 30 days and disabled the higher-of test — wrong on both counts.",
            ),
        },
        "resignationBenefitBands": r(
            [{"fromYears": 1, "toYears": 3, "daysPerYear": 7},
             {"fromYears": 3, "toYears": 10, "daysPerYear": 15},
             {"fromYears": 10, "toYears": None, "daysPerYear": 30, "higherOfGratuity": True}],
            X, c["resignation"],
        ),
        "noticePeriodDaysByCategoryAndPayBasis": r(
            {"PERMANENT": {"MONTHLY": 120, "OTHER": 60}, "TEMPORARY": {"MONTHLY": 30, "OTHER": 14}},
            V, f"{BLA}, s.26", "Was 120 / 30 with no pay-basis split.",
        ),
        "resignationNoticeDays": r({"PERMANENT": 60, "TEMPORARY_MONTHLY": 30, "TEMPORARY_OTHER": 14}, V, f"{BLA}, s.27"),
        "retirementAge": r(60, V, f"{BLA}, s.28", "Raised from 57 by the 2013 amendment. The 57 figure still circulates and is obsolete."),
        "deathCompensationEligibilityYears": r(1, V, c["death"], "Was 2 years."),
        "dismissalProcedure": r(
            {"chargeReplyDays": 7, "suspensionCapDays": 60}, V, f"{BLA}, s.24",
            "Without this procedure a dismissal is void, whatever the merits.",
        ),
        "finalSettlementWorkingDays": r(30, V, c["wagePayment"]),
        "continuousServiceDays": r(
            {"inTwelveMonths": 240, "inSixMonths": 120}, D, c["continuousService"],
            "Gates lay-off, gratuity and every compensation threshold — must be computed, not assumed.",
        ),
        # RB-SEP lay-off — absent from the prototype entirely.
        "layoff": {
            "eligibilityMonths": r(3, V, c["layoff"], "Was 1 year."),
            "rateOfBasicAndDa": r("0.5", V, c["layoff"]),
            "housingAllowanceRate": r("1.0", V, c["layoff"]),
            "annualCapDays": r(45, X, f"{BLA}, s.16(4)", "Whether the 2026 amendment’s 50%-of-basic floor displaces the 25% tail beyond 45 days is unresolved."),
            "tailRateOfBasicAndDa": r("0.25", X, c["layoff"]),
            "tailBlockMinimumDays": r(15, C, c["layoff"]),
            "triggerAfterWorkingDays": r(3, C, c["layoff"]),
        },
        # RB-WAGE / RB-GOV
        "wageRevisionCycleYears": r(3, C, "Minimum Wages Board", "Was 5 years."),
        "workerDefinitionBasis": r("WORK_PERFORMED", V, c["classification"], "Designation-blind since the 2026 amendment."),
        "aggregateDeductionCapPercent": r(
            None, D, f"{BLA}, s.125",
            "The 50%-of-wages aggregate cap everyone assumes probably does not exist — it comes from the repealed "
            "Payment of Wages Act 1936. The Labour Act’s limits are per-head.",
        ),
        "accommodationEvictionNoticeMonths": r(6, V, f"{BLA}, s.32A", "Was 60 days."),
        "complaintCommittee": r({"members": 5, "womanChair": True, "womenMajority": True}, V, c["complaintCommittee"]),
        "safetyCommittee": r({"mandatoryAtWorkers": 50}, V, c["safetyCommittee"]),
        "unionCheckOffDepositDays": r(15, V, c["unionCheckOff"]),
        "penalties": {
            "general": r({"min": 25000, "max": 50000, "imprisonmentMonths": 3}, V, f"{BLA}, s.307", "Was Tk 5,000."),
            "minimumWageNonPayment": r({"min": 50000, "max": 100000, "imprisonmentMonths": 12}, V, f"{BLA}, s.289(1)"),
        },
        "citations": citations,
    })
    return out


def rule_sets():
    """Every BD rule set, as keyword arguments for `RuleSet`."""
    return [
        dict(family="TAX", version="2025-26", effective_from=date(2025, 7, 1), effective_to=date(2026, 6, 30),
             source="Finance Act 2025", data=deepcopy(TAX_2025_26)),
        dict(family="TAX", version="2026-27", effective_from=date(2026, 7, 1), effective_to=date(2027, 6, 30),
             source="Finance Act 2026", data=deepcopy(TAX_2026_27)),
        dict(family="TAX", version="2028-29", effective_from=date(2028, 7, 1), effective_to=date(2029, 6, 30),
             source="Finance Act 2026", data=deepcopy(TAX_2028_29)),
        dict(family="TAX", version="2030-31", effective_from=date(2030, 7, 1), effective_to=date(2031, 6, 30),
             source="Finance Act 2026", data=deepcopy(TAX_2030_31)),
        dict(family="LABOUR", version="2015-09-01", effective_from=date(2015, 9, 1), effective_to=date(2026, 4, 9),
             source="Bangladesh Labour Act 2006 · Bangladesh Labour Rules 2015", data=_labour_2015()),
        dict(family="LABOUR", version="2026-04-10", effective_from=date(2026, 4, 10), effective_to=None,
             source="Labour (Amendment) Act 2026 (Act 43 of 2026) · Bangladesh Labour Act 2006 as amended",
             data=_labour_2026()),
    ]


def assert_enum_coverage(sets):
    """Every enum value has a rule (rules.js `assertEnumCoverage`). Throws loudly."""
    for spec in sets:
        data = spec["data"]
        if spec["family"] == "TAX":
            for category in TAXPAYER_CATEGORIES:
                if category not in data["taxFreeThresholds"]:
                    raise ValueError(f"{spec['version']}: no tax-free threshold for {category}")
        else:
            for establishment in ESTABLISHMENTS:
                for key in ("earnedLeaveRatioByEstablishment", "accumulationCapByEstablishment"):
                    if establishment not in data[key]["value"]:
                        raise ValueError(f"{spec['version']}: {key} missing {establishment}")
            for separation in SEPARATION_TYPES:
                if separation not in data["compensationDaysPerYearBySeparationType"]:
                    raise ValueError(f"{spec['version']}: no compensation rule for {separation}")
            for category in WORKER_CATEGORIES:
                if category not in data["noticePeriodDaysByWorkerCategory"]["value"]:
                    raise ValueError(f"{spec['version']}: no notice period for {category}")
