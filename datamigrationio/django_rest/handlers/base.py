class BaseMigrationHandler:
    data_type: str = ""
    label: str = ""
    category: str = ""
    description: str = ""
    has_gl_impact: bool = False
    is_posting_transaction: bool = False
    import_available: bool = False
    template_available: bool = True

    @classmethod
    def get_metadata(cls) -> dict:
        meta = {
            "data_type": cls.data_type,
            "label": cls.label,
            "category": cls.category,
            "description": cls.description,
            "has_gl_impact": cls.has_gl_impact,
            "is_posting_transaction": cls.is_posting_transaction,
            "import_available": cls.import_available,
            "template_available": cls.template_available,
            "target_fields": cls.get_target_fields(),
            "required_target_fields": sorted(cls.get_required_target_fields()),
            "accounting_target_fields": sorted(cls.get_accounting_target_fields()),
        }
        if not cls.import_available:
            meta["message"] = (
                "This migration type is registered for future support, "
                "but import is not implemented yet."
            )
        return meta

    @classmethod
    def get_template_headers(cls) -> list:
        return []

    @classmethod
    def get_template_sample_row(cls) -> list:
        return []

    @classmethod
    def generate_template_response(cls):
        """Override in subclasses to provide a custom template response (e.g. xlsx)."""
        return None

    @classmethod
    def get_field_aliases(cls) -> dict:
        return {}

    @classmethod
    def get_target_fields(cls) -> list:
        return list(set(cls.get_field_aliases().values()))

    @classmethod
    def get_required_target_fields(cls) -> set:
        return set()

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return set()

    @classmethod
    def validate(cls, job, company) -> dict:
        return {
            "implemented": False,
            "detail": "Validation is not implemented yet for this migration type.",
            "data_type": cls.data_type,
            "import_available": False,
        }

    @classmethod
    def review_impact(cls, job, company) -> dict:
        return {
            "implemented": False,
            "detail": "Accounting impact is not implemented yet for this migration type.",
            "data_type": cls.data_type,
            "import_available": False,
        }

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        return {
            "implemented": False,
            "detail": "Import is not implemented yet for this migration type.",
            "data_type": cls.data_type,
            "import_available": False,
        }

    @classmethod
    def rollback(cls, job, user, reason="") -> dict:
        return {
            "implemented": False,
            "detail": "Rollback is not implemented yet for this migration type.",
            "data_type": cls.data_type,
            "import_available": False,
        }
