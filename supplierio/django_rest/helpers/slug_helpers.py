def get_suplier_slug(instance):
    return f"supplier-{instance.first_name}-{str(instance.uid).split('-')[0]}"
