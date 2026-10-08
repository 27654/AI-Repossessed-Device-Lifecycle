import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0004_attachment_assessment'),
        ('refurbishment', '0002_reference_sequence_history_triggers'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='attachment',
            name='attachment_single_lifecycle_link',
        ),
        migrations.AddField(
            model_name='attachment',
            name='refurbishment',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='attachments', to='refurbishment.refurbishmentworkorder'),
        ),
        migrations.AddConstraint(
            model_name='attachment',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('recovery__isnull', True), ('assessment__isnull', True)), models.Q(('recovery__isnull', True), ('refurbishment__isnull', True)), models.Q(('assessment__isnull', True), ('refurbishment__isnull', True)), _connector='OR'), name='attachment_single_lifecycle_link_v2'),
        ),
    ]
