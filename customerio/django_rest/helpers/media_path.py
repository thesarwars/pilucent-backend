def get_customer_media_path_prefix(instance, filename):
    return f"customer/{instance.first_name}/{filename}"
