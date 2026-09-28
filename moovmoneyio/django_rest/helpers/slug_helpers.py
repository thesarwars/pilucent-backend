def get_moov_account_setting_slug(instance):
    return f"moov_account_setting-{str(instance.uid).split('-')[0]}"

def get_moov_bank_account_setting_slug(instance):
    return f"moov_bank_account_setting-{str(instance.uid).split('-')[0]}"


def get_moov_transfer_slug(instance):
    return f"moov_transfer-{str(instance.uid).split('-')[0]}"

