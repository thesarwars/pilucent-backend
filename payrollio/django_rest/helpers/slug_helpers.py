def get_salary_adjustment_slug(instance):
    return f"salary_adjustment-{str(instance.uid).split('-')[0]}"

def get_dedcon_slug(instance):
    return f"ded_con-{str(instance.uid).split('-')[0]}"

def get_pay_schedule_slug(instance):
    return f"pay_schedule-{str(instance.uid).split('-')[0]}"

def get_payroll_salary_process_slug(instance):
    return f"salary_process-{str(instance.uid).split('-')[0]}"

def get_payroll_salary_component_slug(instance):
    return f"salary_component-{str(instance.uid).split('-')[0]}"

def get_payroll_general_tax_setting_slug(instance):
    return f"general_tax_setting-{str(instance.uid).split('-')[0]}"

def get_payroll_federal_tax_info_setting_slug(instance):
    return f"federal_tax_info_setting-{str(instance.uid).split('-')[0]}"

def get_payroll_state_tax_info_setting_slug(instance):
    return f"state_tax_info_setting-{str(instance.uid).split('-')[0]}"


def get_payroll_general_tax_setting_slug(instance):
    return f"general_tax_setting-{str(instance.uid).split('-')[0]}"

def get_payroll_work_location_slug(instance):
    return f"work_location-{str(instance.uid).split('-')[0]}"

def get_payroll_accounting_preferences_slug(instance):
    return f"accounting_preferences-{str(instance.uid).split('-')[0]}"

def get_payroll_contact_info_setting_slug(instance):
    return f"payroll_contact-{str(instance.uid).split('-')[0]}"