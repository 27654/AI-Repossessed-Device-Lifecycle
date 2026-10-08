"""Database-side guarantees for refurbishment.

- `refurbishment_workorder_reference_seq` numbers work orders
  (REF-<year>-<number>) without races between concurrent requests.
- A closed work order (COMPLETED or CANCELLED) is history: UPDATE is
  rejected. No work order, step or item can be deleted.
- Steps: a finished step (COMPLETED or SKIPPED) cannot change, and no step of
  a closed work order can change.
- Items: no item of a closed work order can change.

TRUNCATE stays possible for `manage.py flush` and tests.
"""

from django.db import migrations

CREATE = """
CREATE SEQUENCE IF NOT EXISTS refurbishment_workorder_reference_seq START 1;

CREATE OR REPLACE FUNCTION refurbishment_workorder_protect() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status IN ('OPEN', 'IN_PROGRESS') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'refurbishment work order: % of a closed or recorded work order is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER refurbishment_workorder_protect
    BEFORE UPDATE OR DELETE ON refurbishment_refurbishmentworkorder
    FOR EACH ROW EXECUTE FUNCTION refurbishment_workorder_protect();

CREATE OR REPLACE FUNCTION refurbishment_step_protect() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.status NOT IN ('COMPLETED', 'SKIPPED')
       AND (SELECT status FROM refurbishment_refurbishmentworkorder WHERE id = OLD.work_order_id)
           IN ('OPEN', 'IN_PROGRESS') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'refurbishment step: % of a finished step or a closed work order is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER refurbishment_step_protect
    BEFORE UPDATE OR DELETE ON refurbishment_refurbishmentstep
    FOR EACH ROW EXECUTE FUNCTION refurbishment_step_protect();

CREATE OR REPLACE FUNCTION refurbishment_item_protect() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND (SELECT status FROM refurbishment_refurbishmentworkorder WHERE id = OLD.work_order_id)
           IN ('OPEN', 'IN_PROGRESS') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'refurbishment item: % of a part on a closed work order is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER refurbishment_item_protect
    BEFORE UPDATE OR DELETE ON refurbishment_refurbishmentitem
    FOR EACH ROW EXECUTE FUNCTION refurbishment_item_protect();
"""

DROP = """
DROP TRIGGER IF EXISTS refurbishment_item_protect ON refurbishment_refurbishmentitem;
DROP FUNCTION IF EXISTS refurbishment_item_protect();
DROP TRIGGER IF EXISTS refurbishment_step_protect ON refurbishment_refurbishmentstep;
DROP FUNCTION IF EXISTS refurbishment_step_protect();
DROP FUNCTION IF EXISTS refurbishment_child_protect();
DROP TRIGGER IF EXISTS refurbishment_workorder_protect ON refurbishment_refurbishmentworkorder;
DROP FUNCTION IF EXISTS refurbishment_workorder_protect();
DROP SEQUENCE IF EXISTS refurbishment_workorder_reference_seq;
"""


class Migration(migrations.Migration):
    dependencies = [("refurbishment", "0001_refurbishment")]

    operations = [migrations.RunSQL(CREATE, DROP)]
