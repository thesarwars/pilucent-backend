from rest_framework.serializers import ModelSerializer, SerializerMethodField

from categoryio.models import Category


class PublicCategoryChartOfAccountListSerializer(ModelSerializer):
    # options = SerializerMethodField()

    class Meta:
        model = Category
        fields = ["slug", "title", "created_at", "updated_at"]

    # def get_options(self, instance):
    #     return PublicCategoryChartOfAccountListSerializer(
    #         instance.parents.all(), many=True, read_only=True
    #     ).data
    
class PublicCategoryChartOfAccountDetailsSerializer(ModelSerializer):
    options = SerializerMethodField()

    class Meta:
        model = Category
        fields = ["slug", "title", "options", "created_at", "updated_at"]

    def get_options(self, instance):
        return PublicCategoryChartOfAccountListSerializer(
            instance.parents.all(), many=True, read_only=True
        ).data
