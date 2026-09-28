def get_category_slug(instance):
    return f"category-{str(instance.uid).split('-')[0]}"


def get_category_connector_slug(instance):
    return f"category_connector-{str(instance.uid).split('-')[0]}"
