"""Database-side guarantees for AI decision support.

ai_engine_airecommendation:
- The AI output columns never change after the row is created.
- The human final decision is written once: an UPDATE is allowed only while
  final_decision is empty, and may only fill the decision columns.
- Rows cannot be deleted.

ai_engine_aifeedback: append-only (no UPDATE or DELETE).

TRUNCATE stays possible for `manage.py flush` and tests.
"""

from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION ai_engine_airecommendation_protect() RETURNS trigger AS $$
DECLARE
    DECISION_COLUMNS CONSTANT text[] := ARRAY[
    'final_decision', 'final_decision_by_id', 'final_decision_at', 'final_decision_reason'];
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.final_decision = ''
       AND (to_jsonb(NEW) - DECISION_COLUMNS) = (to_jsonb(OLD) - DECISION_COLUMNS) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'ai_engine_airecommendation: AI output is immutable and the final decision is write-once (% refused)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_engine_airecommendation_protect
    BEFORE UPDATE OR DELETE ON ai_engine_airecommendation
    FOR EACH ROW EXECUTE FUNCTION ai_engine_airecommendation_protect();

CREATE OR REPLACE FUNCTION ai_engine_aifeedback_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ai_engine_aifeedback is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_engine_aifeedback_append_only
    BEFORE UPDATE OR DELETE ON ai_engine_aifeedback
    FOR EACH ROW EXECUTE FUNCTION ai_engine_aifeedback_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS ai_engine_aifeedback_append_only ON ai_engine_aifeedback;
DROP FUNCTION IF EXISTS ai_engine_aifeedback_append_only();
DROP TRIGGER IF EXISTS ai_engine_airecommendation_protect ON ai_engine_airecommendation;
DROP FUNCTION IF EXISTS ai_engine_airecommendation_protect();
"""


class Migration(migrations.Migration):
    dependencies = [("ai_engine", "0001_ai_recommendation_feedback")]

    operations = [migrations.RunSQL(CREATE, DROP)]
