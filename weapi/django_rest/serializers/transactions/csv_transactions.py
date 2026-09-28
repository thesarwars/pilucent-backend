from rest_framework import serializers
from django.db.models import Sum, Q, Count

from transactionio.models import TransactionInformation
from transactionio.django_rest.helpers.transaction_rule_apply import (
    apply_rules_for_transactions,
)
from accounts.models import ChartOfAccount
from journalio.models import JournalEntry, JournalEntryConnector

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from companyio.django_rest.serializers.common import PrivateWeCompanySlimSerializer

from transactionio.django_rest.helpers.transaction_matching import (
    get_transaction_match_details,
)

from common.django_rest.helpers.balance_helpers import update_opening_balance

from journalio.choices import JournalEntryStatusChoices

from weapi.django_rest.helpers.journal_entry_posting import (
    void_manual_journal_entry,
)
from decimal import Decimal


class TransactionWrapperSerializer(serializers.ModelSerializer):
    company = PrivateWeCompanySlimSerializer(read_only=True)
    chart_of_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    # `read_only=True` on the declaration, not in `read_only_fields`. DRF
    # short-circuits explicitly declared fields before it consults
    # `extra_kwargs`, so listing a declared field in `read_only_fields` does
    # nothing at all -- this field was named there (below) and stayed writable,
    # against a queryset of every journal entry in the database, so an import
    # could bind its rows to another tenant's entry.
    journal_entry = serializers.SlugRelatedField(
        slug_field="uid",
        read_only=True,
    )
    # `uid` stays writable, deliberately. It is the upsert key: the update path
    # resolves each row by `TransactionInformation.objects.get(uid=trx_uid,
    # company=company)`, so a read-only `uid` would strip the lookup value out
    # of `validated_data` and break every update. It was listed in
    # `read_only_fields` below, which was simply untrue -- removed there rather
    # than enforced here.
    uid = serializers.CharField(required=False)

    class Meta:
        model = TransactionInformation
        fields = [
            "uid",
            "date",
            "description",
            "received",
            "spent",
            "category",
            "payee",
            "is_spam",
            "is_matched",
            "transaction_status",
            "company",
            "chart_of_account",
            "check_number",
            "journal_entry",
        ]
        read_only_fields = [
            # `uid` is NOT here: it is the upsert key and must stay writable.
            # See the note on its declaration above.
            "created_at",
            "updated_at",
            "company",
            "chart_of_account",
            # Reconciliation state, set by the server and never by the client.
            #
            # This serializer looks read-only -- its only view is a
            # ListAPIView -- but `UpsertCSVTransactionsSerializer` nests it as
            # `transactions = TransactionWrapperSerializer(many=True)` and then
            # splats the result straight into the model:
            #
            #     TransactionInformation(**trx, company=..., chart_of_account=...)
            #
            # so every field it accepts is written. `is_matched` is what
            # `reconciliation.cleared_totals()` sums to derive the difference
            # the finish guard refuses to close on, which means a client could
            # not bypass that guard by calling elsewhere -- they could
            # pre-cook the input it reads until the difference came out zero.
            #
            # All three default safely (False / FOR_REVIEW / null), so a CSV
            # import that stops sending them is unaffected.
            # `journal_entry` is not listed here either -- being declared, it
            # would be ignored. It carries `read_only=True` on the declaration.
            "is_matched",
            "transaction_status",
        ]

    def validate(self, attrs):
        """A statement line is money in or money out, and not negative.

        The database enforces this too (BR-18), and that is the guarantee. This
        exists so a client that sends a bad row gets a 400 naming the field
        instead of an IntegrityError surfacing as a 500 -- an import of a
        thousand rows should say which one is wrong.

        Only the keys actually supplied are checked, because this serializer is
        used for partial updates as well as creation, and a row that omits an
        amount is not asserting anything about it.
        """
        received = attrs.get("received")
        spent = attrs.get("spent")

        errors = {}
        if received is not None and received < 0:
            errors["received"] = "A receipt cannot be negative."
        if spent is not None and spent < 0:
            errors["spent"] = "A payment cannot be negative."
        if received and spent and received > 0 and spent > 0:
            errors["non_field_errors"] = (
                "A statement line is either money in or money out, not both. "
                f"Got received={received} and spent={spent}."
            )
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        match_details = get_transaction_match_details(instance)
        data["match_count"] = match_details["match_count"]
        data["matched_items"] = match_details["matched_items"]
        return data


class UpsertCSVTransactionsSerializer(serializers.Serializer):
    """
    Serializer for handling the upload of CSV transactions.
    """

    transactions = TransactionWrapperSerializer(many=True)
    chart_of_account = serializers.CharField()
    undo = serializers.BooleanField(required=False)

    def validate_chart_of_account(self, value):
        """The bank account these rows belong to, scoped to the caller.

        Was `ChartOfAccount.objects.get(uid=value)`, which had two faults. It
        resolved any tenant's account -- `accounts_chartofaccount` carries RLS
        so the row would not come back inside a scoped request, but a serializer
        should not depend on the database to do its filtering. And `.get()`
        raises `DoesNotExist`, which nothing converts, so an unknown or
        mistyped uid was a 500 rather than a message naming the field.

        Narrowed with `selectable()` like every other account picker, because
        importing rows into an account is data entry: a retired account keeps
        its history and its place on the reports but is not offered for new
        activity, and a parent with children is a summarising header that
        should not receive lines directly (COA-131).
        """
        company = self.context.get("company")
        candidates = ChartOfAccount.objects.selectable()
        if company is not None:
            candidates = candidates.filter(company=company)

        account = candidates.filter(uid=value).first()
        if account is None:
            raise serializers.ValidationError(
                "No such account in this company, or it is retired or a "
                "summary account that cannot take transactions."
            )
        return account

    def create(self, validated_data):
        """
        Create a new transaction instance.
        """
        chart_of_account = validated_data.get("chart_of_account")
        trx_data = validated_data.get("transactions")
        company = self.context.get("company")
        trx_objects = [
            TransactionInformation(
                **trx, company=company, chart_of_account=chart_of_account
            )
            for trx in trx_data
        ]
        created_objects = TransactionInformation.objects.bulk_create(trx_objects)
        company_uid = str(company.uid)
        transaction_uids = [str(trx.uid) for trx in created_objects]

        apply_rules_for_transactions(
            company_uid=company_uid, transaction_uids=transaction_uids
        )

        created_objects = list(
            TransactionInformation.objects.filter(
                uid__in=transaction_uids
            ).select_related("chart_of_account", "company", "journal_entry")
        )

        return {"transactions": created_objects}

    def to_representation(self, instance):
        return {
            "transactions": TransactionWrapperSerializer(
                instance["transactions"], many=True
            ).data
        }

    # The fields the undo path assigns. Named, not derived.
    #
    # This is BR-19, and it is worth stating plainly because the cause was one
    # of our own fixes. `bulk_update` was called with
    # `fields=[f for f in trx_data[0] if f != "uid"]` -- the column list taken
    # from the CLIENT's payload keys. When `f16e0044` correctly made
    # `is_matched`, `transaction_status` and `journal_entry` read-only, DRF
    # stopped putting them in `validated_data`, so they stopped appearing in
    # that derived list, so the undo silently persisted none of the three fields
    # it assigns. Making a field read-only disabled a write path that was
    # reading its own column list from the client.
    #
    # `apply_excluded` in `transaction_rule_apply.py:190-194` already does it
    # this way. This path was the outlier.
    UNDO_FIELDS = ["is_matched", "journal_entry", "transaction_status", "updated_at"]

    def update(self, instance, validated_data):
        trx_data = validated_data.get("transactions") or []
        company = self.context.get("company")
        undo = validated_data.get("undo")

        trx_objects = []
        if undo:
            for trx in trx_data:
                trx_uid = trx.get("uid")
                trx_instance = TransactionInformation.objects.filter(
                    uid=trx_uid, company=company
                ).first()
                if trx_instance is None:
                    # BR-21. `.first()` returns None for a uid that is unknown,
                    # malformed, or another tenant's -- and the next line
                    # dereferenced it, so any of those was a 500. Skipping
                    # matches the non-undo branch below, which already
                    # `continue`s on DoesNotExist.
                    continue

                # Reverse the categorisation: unwind the ledger it posted, then
                # reset the row.
                #
                # There used to be a branch here that skipped the reversal when
                # `is_matched` was true. It is gone because the flag can no
                # longer be true: the reconciliation close path set it until
                # Phase 3 moved the cleared marker onto `JournalEntryConnector`,
                # and both serializers that expose the field made it read-only
                # in Phase 0. Nothing in the codebase assigns `is_matched=True`
                # any more. Leaving a branch that skips the ledger reversal
                # would be a trap for whoever re-introduces a writer.
                if trx_instance.journal_entry:
                    # This loop used to hard-code the leg's accounting side as
                    # the balance operation:
                    #
                    #     if kind == "DEBIT":
                    #         update_opening_balance(acc, "DEBIT", debit, 0)
                    #
                    # `update_opening_balance`'s second argument is NOT a side.
                    # It is add/subtract against the stored balance in the
                    # account's own direction, and its docstring says so. On
                    # ASSETS and EXPENSES a DEBIT leg posts an addition, so
                    # undoing with DEBIT subtracts and lands correctly. On
                    # LIABILITIES, EQUITIES and INCOMES a DEBIT leg posts a
                    # SUBTRACTION -- so undoing with DEBIT subtracted a second
                    # time, moving the balance by twice the amount in the wrong
                    # direction. Five of the ten kind x side combinations were
                    # wrong, which is the same shape as the payroll `_post_side`
                    # defect that produced the exact sign inversions repaired on
                    # production in `49c21e97`.
                    #
                    # And it then hard-deleted the entry, so nothing survived to
                    # measure the damage against -- defect §1 of
                    # LEDGER_WRITE_PATH_GAPS, in the one place still doing it.
                    #
                    # `void_manual_journal_entry` derives the operation from the
                    # leg's side against its account's kind and posts a REMOVED
                    # reversal rather than erasing. The original is retired
                    # alongside it, so the pair nets to zero on both readings of
                    # the ledger and shows on neither -- the same contract the
                    # manual journal-entry delete settled on.
                    entry = trx_instance.journal_entry
                    void_manual_journal_entry(entry)
                    entry.status = JournalEntryStatusChoices.REMOVED
                    entry.save(update_fields=["status"])

                trx_instance.is_matched = False
                trx_instance.transaction_status = "FOR_REVIEW"
                trx_instance.journal_entry = None
                trx_objects.append(trx_instance)

            if trx_objects:
                TransactionInformation.objects.bulk_update(
                    trx_objects, fields=self.UNDO_FIELDS
                )
            return trx_objects

        for trx in trx_data:
            trx_uid = trx.get("uid")
            try:
                trx_instance = TransactionInformation.objects.get(
                    uid=trx_uid, company=company
                )
            except TransactionInformation.DoesNotExist:
                continue

            if trx_instance:
                for field, value in trx.items():
                    if field != "uid":
                        setattr(trx_instance, field, value)
                # The `trx_instance.journal_entry = journal_entry` that stood
                # here is gone with the client-supplied value that fed it. It
                # could only ever have set the entry the caller named, or None,
                # and `bulk_update` below derives its column list from the
                # payload keys -- so a client that sent no `journal_entry` had
                # the assignment silently dropped, and one that sent another
                # tenant's had it bound.
                trx_objects.append(trx_instance)
        if trx_objects:
            # BR-20. The union across every row, not row 0's keys.
            #
            # The column list was `[f for f in trx_data[0] if f != "uid"]`, so a
            # field only the second row carried was assigned in memory and never
            # written -- a client editing `description` on one line and `payee`
            # on the next silently lost the payee. Writing a column a given row
            # did not send is harmless: that object still holds its current
            # value, so the update is a no-op for it.
            #
            # `trx_data[0]` was also an unguarded index into a list the client
            # controls, which made an empty `transactions` array an IndexError
            # (BR-21). The `if trx_objects` above cannot be reached with an
            # empty list, and `fields` is checked below because a payload of
            # nothing but uids yields no columns at all -- `bulk_update` raises
            # "Field names must be given" on an empty list.
            fields = sorted({key for row in trx_data for key in row if key != "uid"})
            if fields:
                TransactionInformation.objects.bulk_update(
                    trx_objects, fields=fields
                )
        return trx_objects


class TransactionSummarySerializer(serializers.ModelSerializer):
    """
    Serializer for handling the summary of transactions.
    """

    # company = PrivateWeCompanySlimSerializer(read_only=True)
    chart_of_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    class Meta:
        model = TransactionInformation
        fields = [
            "uid",
            "transaction_status",
            "chart_of_account",
        ]
        read_only_fields = ["uid", "created_at", "updated_at", "chart_of_account"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        chart_of_account = instance.chart_of_account
        if chart_of_account:
            data["status_for_review"] = TransactionInformation.objects.filter(
                chart_of_account=chart_of_account,
                company=instance.company,
                transaction_status="FOR_REVIEW",
            ).count()
        else:
            data["status_for_review"] = 0
        return data


class TransactionDataUpdateSerializer(serializers.ModelSerializer):
    company = PrivateWeCompanySlimSerializer(read_only=True)
    chart_of_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    journal_entry = serializers.CharField()

    class Meta:
        model = TransactionInformation
        fields = [
            "uid",
            "date",
            "description",
            "received",
            "spent",
            "category",
            "payee",
            "is_spam",
            "is_matched",
            "transaction_status",
            "company",
            "chart_of_account",
            "check_number",
            "journal_entry",
        ]
        read_only_fields = [
            "uid",
            "created_at",
            "updated_at",
            "company",
            "chart_of_account",
        ]

    def update(self, instance, validated_data):
        je_uid = validated_data.get("journal_entry")
        journal_entry = JournalEntry.objects.get(uid=je_uid) if je_uid else None
        instance.journal_entry = journal_entry
        instance.save()
        return instance
