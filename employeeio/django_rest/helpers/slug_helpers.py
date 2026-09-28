def get_employee_notice_period_slug(instance):
    return f"employee-notice-period-{str(instance.uid).split('-')[0]}"


def get_employee_slug(instance):
    return f"employee-{instance.code}-{str(instance.uid).split('-')[0]}"


def get_employee_salary_slug(instance):
    return f"salary-{str(instance.uid).split('-')[0]}"


def get_employee_banking_information_slug(instance):
    return f"banking-information-{str(instance.uid).split('-')[0]}"


def get_employee_education(instance):
    return f"employee-education-{str(instance.uid).split('-')[0]}"


def get_employee_tax(instance):
    return f"employee-tax-{str(instance.uid).split('-')[0]}"


def get_employee_earning_tax(instance):
    return f"employee-earning-{str(instance.uid).split('-')[0]}"


def get_employee_deduction_and_contribution(instance):
    return f"employee-deduction-contribution-{str(instance.uid).split('-')[0]}"

def get_employee_work_experience_slug(instance):
    return f"employee-work-experience-{str(instance.uid).split('-')[0]}"


def get_employee_expense_report_slug(instance):
    return f"employee-expense-report-{str(instance.uid).split('-')[0]}"

