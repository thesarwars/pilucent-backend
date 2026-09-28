from decimal import Decimal

from rest_framework.serializers import ModelSerializer, SerializerMethodField

from accounts.models import ChartOfAccount


class PrivateWeProfitLossListSerializer(ModelSerializer):
    opening_balance = SerializerMethodField()

    def get_opening_balance(self, obj):
        """The account's movement over the requested period.

        Keeps the key `opening_balance` because that is the frontend contract,
        but the figure is no longer the model field of that name. That field is
        a lifetime running balance with no date axis, so on a date-ranged P&L
        every row printed its whole-life total while claiming to be the period
        -- and the rows therefore did not add up to the totals above them once
        those moved to the journal.

        Falls back to the stored column when no period map is supplied, so any
        caller rendering this serializer outside the P&L view is unchanged.
        """
        amounts = self.context.get("period_amounts")
        if amounts is None:
            return obj.opening_balance
        return amounts.get(str(obj.uid), Decimal("0.00"))

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "kind",
            "opening_balance",
            "created_at",
            "updated_at",
        ]
