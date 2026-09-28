def get_company_slug(instance):
    return f"{instance.name}-{str(instance.uid).split('-')[0]}"


def get_company_shift_slug(instance):
    return f"shift-{instance.code}-{str(instance.uid).split('-')[0]}"


def get_company_department_slug(instance):
    return f"{instance.title}-{instance.code}"


def get_company_section_slug(instance):
    return f"{instance.title}-{str(instance.uid).split('-')[0]}"


def get_company_designation_slug(instance):
    return f"{instance.title}-{str(instance.uid).split('-')[0]}"

def get_company_setting_slug(instance):
    return f"company-setting-{str(instance.uid).split('-')[0]}"
