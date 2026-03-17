from django.db import models
from accounts.models import Asset


class Currency(models.IntegerChoices):
    USD = 1
    EUR = 2
    CHF = 3


class PriceSnapshot(models.Model):
    """
    BTC price at a point in time.
    """
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)
    currency = models.IntegerField(choices=Currency.choices)
    price = models.DecimalField(max_digits=20, decimal_places=2)
    source = models.CharField(max_length=50)
    timestamp = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['asset', 'currency', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.asset.ticker}/{Currency(self.currency).name} {self.price} @ {self.timestamp}"
