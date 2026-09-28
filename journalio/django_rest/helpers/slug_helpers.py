def get_journal_entry_slug(instance):
    return f"journal-entry-{str(instance.uid).split('-')[0]}"


def get_journal_entry_connector_slug(instance):
    return f"journal-entry-connector-{str(instance.uid).split('-')[0]}"
