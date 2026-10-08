"""Database-side guarantees for recoveries.

- `recovery_recovery_reference_seq` numbers recovery references
  (RCV-<year>-<number>) without races between concurrent requests.
- A completed recovery is historical evidence: UPDATE of a completed row and
  DELETE of any row are rejected for every client. TRUNCATE stays possible
  for `manage.py flush` and tests.
"""

from django.db import migrations

CREATE = """
CREATE SEQUENCE IF NOT EXISTS recovery_recovery_reference_seq START 1;

CREATE OR REPLACE FUNCTION recovery_recovery_protect_history() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status <> 'COMPLETED' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'recovery_recovery: % of a completed or recorded recovery is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER recovery_recovery_protect_history
    BEFORE UPDATE OR DELETE ON recovery_recovery
    FOR EACH ROW EXECUTE FUNCTION recovery_recovery_protect_history();
"""

DROP = """
DROP TRIGGER IF EXISTS recovery_recovery_protect_history ON recovery_recovery;
DROP FUNCTION IF EXISTS recovery_recovery_protect_history();
DROP SEQUENCE IF EXISTS recovery_recovery_reference_seq;
"""


class Migration(migrations.Migration):
    dependencies = [("recovery", "0001_recovery")]

    operations = [migrations.RunSQL(CREATE, DROP)]
