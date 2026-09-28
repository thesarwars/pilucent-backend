def get_brand_slug(instance):
    return f"brand-{str(instance.uid).split('-')[0]}"

def get_brand_connector_slug(instance):
    return f"brand-connector-{str(instance.uid).split('-')[0]}"
