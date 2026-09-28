def get_agency_slug(instance):
    return f"agency-{str(instance.uid).split('-')[0]}"

def get_agency_tax_slug(instance):
    return f"agency-tax-{str(instance.uid).split('-')[0]}"

def get_group_tax_slug(instance):
    return f"group-tax-{str(instance.uid).split('-')[0]}"
