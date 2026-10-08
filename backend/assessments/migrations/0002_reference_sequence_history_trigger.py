"""Database-side guarantees for assessments.

- `assessments_assessment_reference_seq` numbers assessment references
  (ASS-<year>-<number>) without races between concurrent requests.
- A submitted assessment is historical evidence: UPDATE of a submitted row
  and DELETE of any row are rejected for every client. TRUNCATE stays
  possible for `manage.py flush` and tests.
"""

from django.db import migrations

CREATE = """
CREATE SEQUENCE IF NOT EXISTS assessments_assessment_reference_seq START 1;

CREATE OR REPLACE FUNCTION assessments_assessment_protect_history() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status <> 'SUBMITTED' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'assessments_assessment: % of a submitted or recorded assessment is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER assessments_assessment_protect_history
    BEFORE UPDATE OR DELETE ON assessments_assessment
    FOR EACH ROW EXECUTE FUNCTION assessments_assessment_protect_history();
"""

DROP = """
DROP TRIGGER IF EXISTS assessments_assessment_protect_history ON assessments_assessment;
DROP FUNCTION IF EXISTS assessments_assessment_protect_history();
DROP SEQUENCE IF EXISTS assessments_assessment_reference_seq;
"""


class Migration(migrations.Migration):
    dependencies = [("assessments", "0001_assessment")]

    operations = [migrations.RunSQL(CREATE, DROP)]
