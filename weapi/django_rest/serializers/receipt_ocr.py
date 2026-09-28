from rest_framework import serializers


class ReceiptParseInputSerializer(serializers.Serializer):
    image = serializers.ImageField(required=True)
