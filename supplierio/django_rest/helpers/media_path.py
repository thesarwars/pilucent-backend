def get_customer_media_path_prefix(instance, filename):
    return f"supplier/{instance.first_name}/{filename}"
