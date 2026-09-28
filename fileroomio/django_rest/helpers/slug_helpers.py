def get_fileitem_slug(instance):
    return f"file-item-{str(instance.uid).split('-')[0]}"

def get_fileitem_connector_slug(instance):
    return f"file-item-connector-{str(instance.uid).split('-')[0]}"
