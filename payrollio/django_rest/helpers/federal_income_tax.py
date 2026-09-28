SINGLE_FEDERAL_TAX_BRACKET_2025 = [
    (0, 11926, 0.10),
    (11926, 48476, 0.12),
    (48476, 103351, 0.22),
    (103351, 197301, 0.24),
    (197301, 250526, 0.32),
    (250526, 626351, 0.35),
    (626351, float("inf"), 0.37),
]

MARRIED_FEDERAL_TAX_BRACKET_2025 = [
    (0, 23851, 0.10),
    (23851, 96951, 0.12),
    (96951, 206701, 0.22),
    (206701, 394601, 0.24),
    (394601, 501051, 0.32),
    (501051, 751601, 0.35),
    (751601, float("inf"), 0.37),
]


NY_STATE_TAX_BRACKET_2025 = [
    (0, 8501, 0.04),
    (8501, 11701, 0.045),
    (11701, 13901, 0.0525),
    (13901, 80651, 0.055),
    (80651, 215401, 0.06),
    (215401, 1077551, 0.0685),
    (1077551, 5000001, 0.0965),
    (5000000, 25000000, 0.103),
    (5000000, float("inf"), 0.109),
]

SALARY_SCHEDULE = {"DAILY": 365, "WEEKLY": 52, "QUARTERLY": 24, "MONTHLY": 12}
PAYROLL = {"gross_pay": 10000}

def calculate_social_security_tax(income):
    tax = 0
    

def calculate_federal_income_tax(income):
    tax = 0
    for lower, upper, rate in NY_STATE_TAX_BRACKET_2025:
        print(f"lower {lower}, upper {upper}, rate {rate}")
        if income > lower:
            taxed_amount = min(income, upper) - lower
            tax += taxed_amount * rate
            print('slab_tax', tax)
        else:
            break
    print(f"Total federal income tax: {(tax/12):.2f}")
    return round((tax/12), 2)


def calculate_payroll_taxes(payroll=PAYROLL, pay_schedule=None):
    pay_sche = SALARY_SCHEDULE.get(pay_schedule)
    payroll_income = (payroll['gross_pay'] * SALARY_SCHEDULE.get(pay_schedule))
    print('payroll_income', payroll_income)
    
    fed_income = calculate_federal_income_tax(payroll_income)
    return fed_income
    
taxes = calculate_payroll_taxes(PAYROLL, 'MONTHLY')
