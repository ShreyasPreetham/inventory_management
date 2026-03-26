from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Product(TimeStampedModel):
    sku = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "sku"]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"


class Inventory(TimeStampedModel):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="inventory",
    )
    available_quantity = models.PositiveIntegerField(default=0)
    last_updated_by = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["product__name"]
        verbose_name_plural = "inventory"

    def __str__(self) -> str:
        return f"{self.product.sku}: {self.available_quantity}"


class Dealer(TimeStampedModel):
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Order(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        DELIVERED = "delivered", "Delivered"

    dealer = models.ForeignKey(
        Dealer,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    order_number = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)

    @classmethod
    def generate_order_number(cls) -> str:
        today = timezone.localdate().strftime("%Y%m%d")
        prefix = f"ORD-{today}-"
        latest = (
            cls.objects.filter(order_number__startswith=prefix)
            .order_by("-order_number")
            .values_list("order_number", flat=True)
            .first()
        )
        next_sequence = 1 if not latest else int(latest.split("-")[-1]) + 1
        return f"{prefix}{next_sequence:04d}"

    def recalculate_total(self, save: bool = True):
        total = sum((item.line_total for item in self.items.all()), Decimal("0.00"))
        self.total_amount = total
        if save:
            self.save(update_fields=["total_amount", "updated_at"])
        return total


class OrderItem(TimeStampedModel):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="unique_product_per_order"),
        ]

    def __str__(self) -> str:
        return f"{self.order.order_number} - {self.product.sku}"

    def save(self, *args, **kwargs):
        self.line_total = Decimal(self.quantity) * Decimal(self.unit_price)
        super().save(*args, **kwargs)


@receiver(post_save, sender=Product)
def ensure_inventory_exists(sender, instance, created, **kwargs):
    if created:
        Inventory.objects.get_or_create(product=instance)
