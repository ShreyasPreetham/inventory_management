from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from .models import Dealer, Inventory, Order, OrderItem, Product


class ProductSerializer(serializers.ModelSerializer):
    stock_quantity = serializers.IntegerField(source="inventory.available_quantity", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "description",
            "unit_price",
            "is_active",
            "stock_quantity",
            "created_at",
            "updated_at",
        ]


class DealerOrderSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ["id", "order_number", "status", "total_amount", "created_at"]


class DealerSerializer(serializers.ModelSerializer):
    orders = DealerOrderSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Dealer
        fields = [
            "id",
            "code",
            "name",
            "email",
            "phone",
            "address",
            "is_active",
            "orders",
            "created_at",
            "updated_at",
        ]

    def validate_phone(self, value):
        if not value.isdigit() or len(value) != 10:
            raise serializers.ValidationError("Phone number must contain exactly 10 digits.")
        return value

    def validate_email(self, value):
        normalized = value.strip().lower()
        if not normalized.endswith("@gmail.com"):
            raise serializers.ValidationError("Email must end with @gmail.com.")
        return normalized


class OrderItemWriteSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class OrderItemReadSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product_id",
            "product_name",
            "sku",
            "quantity",
            "unit_price",
            "line_total",
        ]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemReadSerializer(many=True, read_only=True)
    dealer_name = serializers.CharField(source="dealer.name", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "dealer",
            "dealer_name",
            "status",
            "total_amount",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["order_number", "status", "total_amount", "created_at", "updated_at"]


class OrderWriteSerializer(serializers.ModelSerializer):
    items = OrderItemWriteSerializer(many=True, required=False)

    class Meta:
        model = Order
        fields = ["id", "dealer", "items"]

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        if instance and instance.status != Order.Status.DRAFT:
            raise serializers.ValidationError("Only draft orders can be modified.")
        return attrs

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        with transaction.atomic():
            order = Order.objects.create(**validated_data)
            self._replace_items(order, items_data)
        return order

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            if items_data is not None:
                self._replace_items(instance, items_data)
        return instance

    def _replace_items(self, order: Order, items_data):
        order.items.all().delete()
        created_items = []
        seen_product_ids = set()
        for item_data in items_data:
            product_id = item_data["product_id"]
            if product_id in seen_product_ids:
                raise serializers.ValidationError(f"Duplicate product {product_id} in order items is not allowed.")
            seen_product_ids.add(product_id)
            try:
                product = Product.objects.get(pk=product_id, is_active=True)
            except Product.DoesNotExist as exc:
                raise serializers.ValidationError(f"Product {product_id} does not exist or is inactive.") from exc
            created_items.append(
                OrderItem(
                    order=order,
                    product=product,
                    quantity=item_data["quantity"],
                    unit_price=product.unit_price,
                )
            )
        if created_items:
            OrderItem.objects.bulk_create(created_items)
            refreshed_items = OrderItem.objects.filter(order=order).select_related("product")
            for item in refreshed_items:
                item.line_total = Decimal(item.quantity) * item.unit_price
            OrderItem.objects.bulk_update(refreshed_items, ["line_total"])
        order.recalculate_total()


class InventorySerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="product.id", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = Inventory
        fields = [
            "product_id",
            "sku",
            "product_name",
            "available_quantity",
            "last_updated_by",
            "created_at",
            "updated_at",
        ]


class InventoryAdjustmentSerializer(serializers.Serializer):
    adjustment_quantity = serializers.IntegerField()
    updated_by = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate(self, attrs):
        inventory: Inventory = self.context["inventory"]
        updated_quantity = inventory.available_quantity + attrs["adjustment_quantity"]
        if updated_quantity < 0:
            raise serializers.ValidationError(
                {
                    "adjustment_quantity": (
                        "Inventory adjustment cannot reduce stock below zero."
                    )
                }
            )
        attrs["updated_quantity"] = updated_quantity
        return attrs

    def save(self, **kwargs):
        inventory: Inventory = self.context["inventory"]
        inventory.available_quantity = self.validated_data["updated_quantity"]
        inventory.last_updated_by = self.validated_data.get("updated_by", "")
        inventory.save(update_fields=["available_quantity", "last_updated_by", "updated_at"])
        return inventory
