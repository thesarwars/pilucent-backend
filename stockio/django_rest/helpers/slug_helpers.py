def get_stock_alert_slug(instance):
    return f"stock-alert-{str(instance.uid).split('-')[0]}"


def get_stock_adjustment_slug(instance):
    return f"stock-adjustment-{str(instance.uid).split('-')[0]}"

def get_stock_adjustment_item_slug(instance):
    return f"stock-adjustment-item-{str(instance.uid).split('-')[0]}"
