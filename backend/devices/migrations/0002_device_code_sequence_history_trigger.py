"""Database-side guarantees for devices.

- `devices_device_code_seq` numbers device codes (YRW-<year>-<number>) without
  races between concurrent registrations.
- devices_devicestatuschange is append-only: UPDATE and DELETE are rejected
  for every client. TRUNCATE stays possible for `manage.py flush` and tests.
"""

from django.db import migrations

CREATE = """
CREATE SEQUENCE IF NOT EXISTS devices_device_code_seq START 1;

CREATE OR REPLACE FUNCTION devices_status_history_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'devices_devicestatuschange is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER devices_status_history_append_only
    BEFORE UPDATE OR DELETE ON devices_devicestatuschange
    FOR EACH ROW EXECUTE FUNCTION devices_status_history_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS devices_status_history_append_only ON devices_devicestatuschange;
DROP FUNCTION IF EXISTS devices_status_history_append_only();
DROP SEQUENCE IF EXISTS devices_device_code_seq;
"""


class Migration(migrations.Migration):
    dependencies = [("devices", "0001_device_status_history_attachments")]

    operations = [migrations.RunSQL(CREATE, DROP)]
