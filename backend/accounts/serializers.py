from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import LoginAttempt, Permission, Role, User


class RoleSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["code", "name"]


class CurrentUserSerializer(serializers.ModelSerializer):
    role = RoleSummarySerializer(read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "employee_id",
            "role",
            "permissions",
            "account_status",
            "mfa_enabled",
            "last_login",
            "created_at",
        ]
        read_only_fields = fields

    def get_permissions(self, user):
        return sorted(user.get_permission_codes())


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class MfaCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=10)


class MfaDisableSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    code = serializers.CharField(max_length=10)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate_new_password(self, value):
        validate_password(value, user=self.context["request"].user)
        return value


class AdminSetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate_new_password(self, value):
        validate_password(value, user=self.context.get("target_user"))
        return value


class UserSerializer(serializers.ModelSerializer):
    """User management by a System Administrator."""

    role = serializers.SlugRelatedField(slug_field="code", queryset=Role.objects.all())
    role_name = serializers.CharField(source="role.name", read_only=True)
    password = serializers.CharField(write_only=True, required=False, max_length=128, trim_whitespace=False)

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "employee_id",
            "role",
            "role_name",
            "account_status",
            "mfa_enabled",
            "failed_login_count",
            "locked_until",
            "last_login",
            "created_at",
            "updated_at",
            "password",
        ]
        read_only_fields = [
            "mfa_enabled",
            "failed_login_count",
            "locked_until",
            "last_login",
            "created_at",
            "updated_at",
        ]

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        if self.instance is None:
            password = attrs.get("password")
            if not password:
                raise serializers.ValidationError({"password": "An initial password is required."})
            candidate = User(**{k: v for k, v in attrs.items() if k != "password"})
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": exc.messages}) from exc
        elif "password" in attrs:
            raise serializers.ValidationError({"password": "Use the reset-password endpoint to change a password."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class LoginAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginAttempt
        fields = ["id", "email_attempted", "user", "success", "failure_reason", "ip_address", "user_agent", "created_at"]
        read_only_fields = fields


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["code", "description"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(slug_field="code", many=True, queryset=Permission.objects.all())

    class Meta:
        model = Role
        fields = ["id", "code", "name", "description", "permissions"]
        read_only_fields = ["id", "code"]
