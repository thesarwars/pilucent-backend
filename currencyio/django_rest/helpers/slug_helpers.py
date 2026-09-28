def get_currency_slug(instance):
    return f"currency-{str(instance.uid).split('-')[0]}"


def get_currency_connector_slug(instance):
    return f"currency-connector-{str(instance.uid).split('-')[0]}"
