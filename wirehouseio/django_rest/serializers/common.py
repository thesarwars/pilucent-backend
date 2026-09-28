from rest_framework.serializers import ModelSerializer

from wirehouseio.models import Warehouse

class WarehouseBaseSerializer(ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["title", "short_name", "remark"]
        read_only_fields = fields
        

class PrivateWarehouseSlimSerializer(WarehouseBaseSerializer):
    class Meta:
        model = WarehouseBaseSerializer.Meta.model
        fields = ["uid"] + WarehouseBaseSerializer.Meta.fields
        read_only_fields = fields
        
class PublicWarehouseSlimSerializer(WarehouseBaseSerializer):
    class Meta:
        model = WarehouseBaseSerializer.Meta.model
        fields = ["slug"] + WarehouseBaseSerializer.Meta.fields
        read_only_fields = fields
        