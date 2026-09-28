def get_atachment_slug(instance):
    return f"atachment-{str(instance.uid).split('-')[0]}"