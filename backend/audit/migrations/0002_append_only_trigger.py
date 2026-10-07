"""Make audit_auditlog append-only at the database level.

UPDATE and DELETE are rejected for every client, including raw SQL and the
Django shell. The one allowed UPDATE is ON DELETE SET NULL of `user_id` when a
user row is removed; `user_label` still records who acted. TRUNCATE is not
blocked so `manage.py flush` and test teardown keep working.
"""

from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION audit_auditlog_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
       AND (to_jsonb(NEW) - 'user_id') = (to_jsonb(OLD) - 'user_id') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_auditlog is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditlog_append_only
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_auditlog_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS audit_auditlog_append_only ON audit_auditlog;
DROP FUNCTION IF EXISTS audit_auditlog_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_audit_log")]

    operations = [migrations.RunSQL(CREATE, DROP)]
