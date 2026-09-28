"""Test helpers shared across apps.

Nothing here is imported by production code.
"""


class PreConstraintDataMixin:
    """Let a test build duplicate account titles that the schema now forbids.

    `unique_title_per_company_ci` (accounts migration 0044) stops two live
    accounts sharing a title within one company. That is the point of it -- and
    it also means a test cannot construct the data that the duplicate audit and
    the duplicate repair exist to clean up, because those are tools for rows
    that predate the constraint.

    Mix this in and the index is captured, dropped for the class, and restored
    afterwards from its own DDL. Raw SQL rather than `schema_editor`, which
    SQLite refuses to run inside the transaction a `TestCase` holds open.

    Only for tests that genuinely need duplicates. A test that hits the
    constraint by accident -- most often by creating an account whose title the
    company seed already shipped -- should reuse the seeded row instead, which is
    what production does.
    """

    INDEX = "unique_title_per_company_ci"
    _ddl = None

    @classmethod
    def _index_ddl(cls, cursor):
        if cursor.db.vendor == "sqlite":
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=%s",
                [cls.INDEX],
            )
        else:
            cursor.execute(
                "SELECT indexdef FROM pg_indexes WHERE indexname = %s", [cls.INDEX]
            )
        row = cursor.fetchone()
        return row[0] if row else None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.db import connection

        with connection.cursor() as cursor:
            cls._ddl = cls._index_ddl(cursor)
            if cls._ddl:
                cursor.execute(f"DROP INDEX {cls.INDEX}")

    @classmethod
    def tearDownClass(cls):
        from django.db import connection

        if cls._ddl:
            with connection.cursor() as cursor:
                if not cls._index_ddl(cursor):
                    cursor.execute(cls._ddl)
        super().tearDownClass()
