def get_customer_slug(instance):
    return f"customer-{instance.first_name}-{str(instance.uid).split('-')[0]}"
