def get_data_migrations_jobs_slug(instance):
    return f"data-migration-job-{str(instance.uid).split('-')[0]}"

def get_data_migration_row_slug(instance):
    return f"data-migration-row-{str(instance.uid).split('-')[0]}"

def get_data_migration_field_mapping_slug(instance):
    return f"data-migration-field-mapping-{str(instance.uid).split('-')[0]}"

def get_data_migration_validation_issue_slug(instance):
    return f"data-migration-validation-issue-{str(instance.uid).split('-')[0]}"

def get_data_migration_impact_line_slug(instance):
    return f"data-migration-impact-line-{str(instance.uid).split('-')[0]}"