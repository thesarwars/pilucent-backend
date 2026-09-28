"""Audit -- and optionally revoke -- `is_staff` granted by the old Google signup.

Until the fix in `socailauthio/django_rest/google/views.py`, every account created
through Google sign-in was given `is_staff=True`. `is_staff` is the Django-admin
gate, and those users are also added to the `admin` group, which
`accounts/django_rest/helpers/group_seeds.py` grants `Permission.objects.all()`.
Admin requests never set the `app.company_id` GUC and `common/db/rls.py` is
deliberately permissive when it is unset, so row-level security did not contain
them either -- the combination was cross-tenant read and write.

The code fix stops new accounts getting the flag. It does nothing for accounts
already created; this command is that repair.

**Superusers are never touched.** `accounts/managers.py:40-43` forces
`is_staff=True` on every superuser and raises if it is unset, so a bare
`filter(is_staff=True)` sweeps up the team's own Django admins. Everything here
is scoped to `is_superuser=False`.

`is_admin` is NOT revoked. It means "admin of their own company", is resolved
against `get_active_company()`, and e-mail self-signup sets it too -- revoking it
would break six permission checks for legitimate users. Platform access is
`is_superuser` (`adminio/mixins.py:37`), which no signup path grants.

    python manage.py audit_staff_flags                  # dry run, changes nothing
    python manage.py audit_staff_flags --show-superusers
    python manage.py audit_staff_flags --apply          # revokes, asks first
    python manage.py audit_staff_flags --apply --no-input

Dry run is the default: the command is safe to run against production as-is.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User


class Command(BaseCommand):
    help = "Audit and optionally revoke is_staff granted by the old Google signup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually revoke is_staff. Without this the command only reports.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip the confirmation prompt (for non-interactive runs).",
        )
        parser.add_argument(
            "--show-superusers",
            action="store_true",
            help="Also list superusers, which are excluded from any change.",
        )

    def handle(self, *args, **options):
        # The scoping that keeps real Django admins out of the repair.
        affected = User.objects.filter(is_staff=True, is_superuser=False).order_by(
            "created_at"
        )
        superusers = User.objects.filter(is_superuser=True).order_by("created_at")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("is_staff audit"))
        self.stdout.write(
            f"  affected (is_staff, not superuser) : {affected.count()}"
        )
        self.stdout.write(f"  superusers (never touched)         : {superusers.count()}")
        self.stdout.write("")

        if options["show_superusers"] and superusers.exists():
            self.stdout.write(self.style.MIGRATE_HEADING("Superusers -- excluded"))
            for user in superusers:
                self.stdout.write(f"  {user.email}")
            self.stdout.write("")

        if not affected.exists():
            self.stdout.write(self.style.SUCCESS("Nothing to repair."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Accounts that would lose is_staff"))
        self.stdout.write(f"  {'email':<45} {'is_admin':<9} {'joined':<12} groups")
        for user in affected:
            joined = user.created_at.date().isoformat() if user.created_at else "-"
            groups = ", ".join(user.groups.values_list("name", flat=True)) or "-"
            self.stdout.write(
                f"  {user.email:<45} {str(user.is_admin):<9} {joined:<12} {groups}"
            )
        self.stdout.write("")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run -- nothing changed. Re-run with --apply to revoke."
                )
            )
            return

        if not options["no_input"]:
            self.stdout.write(
                self.style.WARNING(
                    f"About to set is_staff=False on {affected.count()} account(s). "
                    "They keep is_admin and their group membership, so they retain "
                    "admin rights within their own company; they lose the Django "
                    "admin site."
                )
            )
            if input("Type 'yes' to continue: ").strip().lower() != "yes":
                self.stdout.write(self.style.ERROR("Aborted. Nothing changed."))
                return

        # Re-resolve inside the transaction; the queryset above is lazy and the
        # set could have changed between the report and the confirmation.
        with transaction.atomic():
            updated = User.objects.filter(
                is_staff=True, is_superuser=False
            ).update(is_staff=False)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Revoked is_staff on {updated} account(s).")
        )
        remaining = User.objects.filter(is_staff=True, is_superuser=False).count()
        if remaining:
            self.stdout.write(
                self.style.ERROR(f"{remaining} still carry is_staff -- investigate.")
            )
        else:
            self.stdout.write(
                "Verify: a former Google account now gets 403 at /admin/ and "
                "existing superusers still reach it."
            )
