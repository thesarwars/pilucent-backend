def get_product_slug(instance):
    return f"product-{str(instance.uid).split('-')[0]}"


def get_product_bundle_slug(instance):
    return f"product-bundle-{str(instance.uid).split('-')[0]}"

def get_product_setting_slug(instance):
    return f"product-setting-{str(instance.uid).split('-')[0]}"
