import os
import wallets.models
from django.db import migrations, models


def _generate_public_id():
    return os.urandom(16).hex()


def populate_public_ids(apps, schema_editor):
    Wallet = apps.get_model('wallets', 'Wallet')
    for wallet in Wallet.objects.all():
        wallet.public_id = _generate_public_id()
        wallet.save(update_fields=['public_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('wallets', '0005_remove_boltcard_card_name'),
    ]

    operations = [
        # Step 1: Add field as nullable, no unique constraint
        migrations.AddField(
            model_name='wallet',
            name='public_id',
            field=models.CharField(max_length=32, default=wallets.models.generate_public_id, editable=False, null=True),
        ),
        # Step 2: Populate existing rows
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        # Step 3: Make non-nullable and unique
        migrations.AlterField(
            model_name='wallet',
            name='public_id',
            field=models.CharField(max_length=32, default=wallets.models.generate_public_id, editable=False, unique=True),
        ),
    ]
