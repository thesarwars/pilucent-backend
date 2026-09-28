def get_purchase_item_slug(instance):
    return f"purchase-item-{str(instance.uid).split('-')[0]}"


def get_purchase_slug(instance):
    return f"purchase-{str(instance.uid).split('-')[0]}"


def get_expense_slug(instance):
    return f"expense-{str(instance.uid).split('-')[0]}"


def get_expense_connector_slug(instance):
    return (
        f"purchase-expense-{instance.purchase.date}-{str(instance.uid).split('-')[0]}"
    )


def get_purchase_payment_slug(instance):
    return f"purchase-payment-{instance.date}-{str(instance.uid).split('-')[0]}"


def get_purchase_payment_item_slug(instance):
    return f"purchase-payment-item-{str(instance.uid).split('-')[0]}"


def get_purchase_setting_slug(instance):
    return f"purchase-setting-{str(instance.uid).split('-')[0]}"


def get_pay_bill_slug(instance):
    return f"paybill-{str(instance.uid).split('-')[0]}"

def get_pay_bill_item_slug(instance):
    return f"paybill-item-{str(instance.uid).split('-')[0]}"
