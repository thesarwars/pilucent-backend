def get_live_demo_slug(instance):
    return f"live-demo-{str(instance.uid).split('-')[0]}"
