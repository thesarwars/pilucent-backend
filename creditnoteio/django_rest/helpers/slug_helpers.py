def get_credit_note_slug(instance):
    return f"credit-note-{instance.kind}-{str(instance.uid).split('-')[0]}"


def get_credit_note_item_slug(instance):
    return f"credit-status-{instance.status}-{str(instance.uid).split('-')[0]}"
