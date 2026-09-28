def get_warehouse_slug (instance):
    return f"warehouse-{str(instance.uid).split('-')[0]}"
