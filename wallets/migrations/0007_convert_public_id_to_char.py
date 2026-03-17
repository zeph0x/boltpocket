import os
import wallets.models
from django.db import migrations, models


def convert_to_char(apps, schema_editor):
    """Convert UUID column to varchar and populate with random hex."""
    with schema_editor.connection.cursor() as cursor:
        # Drop constraints and indexes on the old UUID column
        cursor.execute("""
            DO $$ DECLARE r RECORD;
            BEGIN
                FOR r IN SELECT conname FROM pg_constraint
                    WHERE conrelid = 'wallets_wallet'::regclass
                    AND conname LIKE '%public_id%'
                LOOP
                    EXECUTE 'ALTER TABLE wallets_wallet DROP CONSTRAINT IF EXISTS ' || r.conname;
                END LOOP;
                FOR r IN SELECT indexname FROM pg_indexes
                    WHERE tablename = 'wallets_wallet' AND indexdef LIKE '%public_id%'
                LOOP
                    EXECUTE 'DROP INDEX IF EXISTS ' || r.indexname;
                END LOOP;
            END $$;
        """)
        # Alter column type
        cursor.execute("""
            ALTER TABLE wallets_wallet
            ALTER COLUMN public_id TYPE varchar(32)
            USING replace(public_id::text, '-', '')
        """)
    # Now populate with fresh random values
    Wallet = apps.get_model('wallets', 'Wallet')
    for wallet in Wallet.objects.all():
        wallet.public_id = os.urandom(16).hex()
        wallet.save(update_fields=['public_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('wallets', '0006_wallet_public_id'),
    ]

    operations = [
        migrations.RunPython(convert_to_char, migrations.RunPython.noop),
        # Now Django can manage the field properly
        migrations.AlterField(
            model_name='wallet',
            name='public_id',
            field=models.CharField(max_length=32, default=wallets.models.generate_public_id, editable=False, unique=True),
        ),
    ]
