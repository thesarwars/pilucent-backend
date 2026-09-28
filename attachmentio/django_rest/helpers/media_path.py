def get_atachment_media_path_prefix(instance, filename):
    return f"company/{instance.company.slug}/attachment/thumbnail/{filename}"
