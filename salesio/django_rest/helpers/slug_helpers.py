def get_sale_slug(instance):
    return f"sale-{str(instance.uid).split('-')[0]}"


def get_sale_item_slug(instance):
    return f"sale-item-{str(instance.uid).split('-')[0]}"


def get_sale_receipt_slug(instance):
    return f"sale-receipt-{str(instance.uid).split('-')[0]}"


def get_sale_receipt_connector_slug(instance):
    return f"{instance.created_at}-{str(instance.uid).split('-')[0]}"


def get_sale_payment_receive_slug(instance):
    return f"sale-payment-recieve-{str(instance.uid).split('-')[0]}"


def get_sale_payment_receive_item_slug(instance):
    return f"sale-payment-recieve-item-{str(instance.uid).split('-')[0]}"

def get_sale_setting_slug(instance):
    return f"sale-setting-{str(instance.uid).split('-')[0]}"


def get_sale_agency_tax_slug(instance):
    return f"sale-agency-tax-{str(instance.uid).split('-')[0]}"