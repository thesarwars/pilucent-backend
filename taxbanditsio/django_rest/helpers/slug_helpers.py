def get_tax_bandits_business_account_slug(instance):
    return f"tb-business-account-{str(instance.uid).split('-')[0]}"

def get_tax_bandits_return_940_slug(instance):
    return f"return-940-{str(instance.uid).split('-')[0]}"

def get_tax_bandits_return_941_slug(instance):
    return f"return-941-{str(instance.uid).split('-')[0]}"