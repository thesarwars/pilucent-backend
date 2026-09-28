from rest_framework import serializers

from payrollio.models import DeductionAndContributions

from companyio.django_rest.serializers.common import PrivateWeCompanySlimSerializer

class DeductionAndContributionSlimSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeductionAndContributions
        fields = [
            'uid',
            'title',
            'deduction_type',
            'sub_type',
            'tax_type',
        ]
        read_only_fields = ['uid', 'slug']
        
    
    def create(self, validated_data):
        company = self.context['company']
        return DeductionAndContributions.objects.create(company=company, **validated_data)
    

class DedConDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeductionAndContributions
        fields = [
            'uid',
            'title',
            'deduction_type',
            'sub_type',
            'tax_type',
        ]
        read_only_fields = ['uid', 'slug']
        
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)