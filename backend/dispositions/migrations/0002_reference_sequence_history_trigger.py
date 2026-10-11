"""Database-side guarantees for dispositions.

- `dispositions_disposition_reference_seq` numbers dispositions
  (DSP-<year>-<number>) without races between concurrent requests.
- A confirmed disposition is final: UPDATE of a confirmed row and DELETE of
  any row are rejected for every client. TRUNCATE stays possible for
  `manage.py flush` and tests.
"""

from django.db import migrations

CREATE = """
CREATE SEQUENCE IF NOT EXISTS dispositions_disposition_reference_seq START 1;

CREATE OR REPLACE FUNCTION dispositions_disposition_protect_history() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status <> 'CONFIRMED' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'dispositions_disposition: % of a confirmed or recorded disposition is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER dispositions_disposition_protect_history
    BEFORE UPDATE OR DELETE ON dispositions_disposition
    FOR EACH ROW EXECUTE FUNCTION dispositions_disposition_protect_history();
"""

DROP = """
DROP TRIGGER IF EXISTS dispositions_disposition_protect_history ON dispositions_disposition;
DROP FUNCTION IF EXISTS dispositions_disposition_protect_history();
DROP SEQUENCE IF EXISTS dispositions_disposition_reference_seq;
"""


class Migration(migrations.Migration):
    dependencies = [("dispositions", "0001_disposition")]

    operations = [migrations.RunSQL(CREATE, DROP)]
