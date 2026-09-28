def get_invoice_slug(instance):
    return f"invoice-{str(instance.uid)[0]}"
