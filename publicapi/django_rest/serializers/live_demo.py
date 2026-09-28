from rest_framework.serializers import ModelSerializer

from livedemoio.models import LiveDemo
from livedemoio.django_rest.helpers.send_email import send_demo_email


class PublicWeLiveDemoCreateSerializer(ModelSerializer):
    class Meta:
        model = LiveDemo
        fields = [
            "uid",
            "email",
            "full_name",
            "phone_number",
            "work_email",
            "company_name",
            "agent_count",
            "preferred_version",
            "preferred_date",
            "preferred_time",
            "comment",
            "status",
            "request_type",
        ]

    read_only_fields = ["uid", "created_at", "updated_at"]


class PublicWeLiveDemoListSerializer(ModelSerializer):
    class Meta:
        model = LiveDemo
        fields = [
            "uid",
            "email",
            "full_name",
            "phone_number",
            "work_email",
            "company_name",
            "created_at",
            "updated_at",
            "agent_count",
            "preferred_version",
            "preferred_date",
            "preferred_time",
            "comment",
            "status",
            "is_mail_sent",
            "request_type",
        ]

    read_only_fields = ["uid", "created_at", "updated_at"]


class PublicWeLiveDemoDetailsSerializer(ModelSerializer):
    class Meta:
        model = LiveDemo
        fields = [
            "uid",
            "email",
            "full_name",
            "phone_number",
            "work_email",
            "company_name",
            "phone_number",
            "agent_count",
            "preferred_version",
            "preferred_date",
            "preferred_time",
            "comment",
            "status",
            "meeting_type",
            "meeting_link",
            "mail_subject",
            "mail_body",
            "is_mail_sent",
        ]

    read_only_fields = ["uid", "email", "created_at", "updated_at"]

    def update(self, instance, validated_data):
        original_meet_url = instance.meeting_link
        # instance.is_mail_sent = validated_data.get("is_mail_sent", instance.is_mail_sent)
        instance.mail_subject = validated_data.get("mail_subject", instance.mail_subject)
        instance.mail_body = validated_data.get("mail_body", instance.mail_body)
        instance.meeeting_type = validated_data.get("meeting_type", instance.meeting_type)
        instance.meeting_link = validated_data.get("meeting_link", original_meet_url)
        instance.status = validated_data.get("status", instance.status)
        
        if instance.meeting_link != original_meet_url:
            mail_status = send_demo_email(
                instance.work_email,
                instance.mail_subject,
                instance.mail_body,
            )
            if mail_status == 1:
                instance.is_mail_sent = True
        print("validated_data", validated_data)
        instance.save()
        return instance