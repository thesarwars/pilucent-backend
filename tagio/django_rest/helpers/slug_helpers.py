def get_tag_slug(instance):
    return f"tag-{str(instance.uid).split('-')[0]}"

def get_tag_connector_slug(instance):
    return f"tag-connector-{str(instance.uid).split('-')[0]}"
