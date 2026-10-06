from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "user",
            "user_label",
            "action",
            "entity_type",
            "entity_id",
            "previous_values",
            "new_values",
            "description",
            "ip_address",
            "user_agent",
            "created_at",
        ]
        read_only_fields = fields
