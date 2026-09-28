def get_address_slug(instance):
    return f"address-{str(instance.uid).split('-')[0]}"


def get_address_connector_slug(instance):
    return f"address-item-{str(instance.uid).split('-')[0]}"
