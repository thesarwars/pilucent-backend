def get_term_connector_slug(instance):
    return f"term-connector-{str(instance.uid).split('-')[0]}"
