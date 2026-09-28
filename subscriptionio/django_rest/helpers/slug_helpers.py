def get_subscription_slug(instance):
    return f"subscription-{str(instance.uid).split('-')[0]}"


def get_subscription_price_slug(instance):
    return f"subscription-price-{instance.billing_frequency}-{str(instance.uid).split('-')[0]}"


def get_company_subscription_slug(instance):
    return f"company-subscription-{str(instance.uid).split('-')[0]}"
