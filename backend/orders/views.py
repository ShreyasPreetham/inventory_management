from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, ProtectedError, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from .models import Dealer, Inventory, Order, Product
from .serializers import (
    DealerSerializer,
    InventoryAdjustmentSerializer,
    InventorySerializer,
    OrderSerializer,
    OrderWriteSerializer,
    ProductSerializer,
)


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("inventory").all()
    serializer_class = ProductSerializer

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Product cannot be deleted because it is referenced by existing orders."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class DealerViewSet(viewsets.ModelViewSet):
    queryset = Dealer.objects.prefetch_related("orders").all()
    serializer_class = DealerSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.select_related("dealer").prefetch_related("items__product").all()

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return OrderWriteSerializer
        return OrderSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        dealer_id = self.request.query_params.get("dealer")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if dealer_id:
            queryset = queryset.filter(dealer_id=dealer_id)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(
            OrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def partial_update(self, request, *args, **kwargs):
        return self._update_with_read_serializer(request, partial=True)

    def update(self, request, *args, **kwargs):
        return self._update_with_read_serializer(request, partial=False)

    def _update_with_read_serializer(self, request, partial: bool):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        return Response(OrderSerializer(order, context={"request": request}).data)

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            order = (
                get_object_or_404(
                    Order.objects.select_for_update()
                    .select_related("dealer")
                    .prefetch_related("items__product"),
                    pk=kwargs.get(self.lookup_url_kwarg or self.lookup_field),
                )
            )

            if order.status == Order.Status.CONFIRMED:
                product_ids = [item.product_id for item in order.items.all()]
                inventory_map = {
                    inventory.product_id: inventory
                    for inventory in Inventory.objects.select_for_update().filter(product_id__in=product_ids)
                }

                for item in order.items.all():
                    inventory = inventory_map.get(item.product_id)
                    if inventory:
                        inventory.available_quantity += item.quantity
                        inventory.save(update_fields=["available_quantity", "updated_at"])

            elif order.status == Order.Status.DELIVERED:
                return Response(
                    {"detail": "Delivered orders cannot be deleted."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            order.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        with transaction.atomic():
            order = (
                get_object_or_404(
                    Order.objects.select_for_update()
                .select_related("dealer")
                .prefetch_related("items__product"),
                    pk=pk,
                )
            )
            if order.status != Order.Status.DRAFT:
                return Response(
                    {"detail": "Only draft orders can be confirmed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not order.items.exists():
                return Response(
                    {"detail": "Cannot confirm an order without items."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            product_ids = [item.product_id for item in order.items.all()]
            inventory_map = {
                inventory.product_id: inventory
                for inventory in Inventory.objects.select_for_update()
                .select_related("product")
                .filter(product_id__in=product_ids)
            }

            insufficient_stock = []
            for item in order.items.all():
                inventory = inventory_map.get(item.product_id)
                available = inventory.available_quantity if inventory else 0
                if item.quantity > available:
                    insufficient_stock.append(
                        {
                            "product_id": item.product_id,
                            "product_name": item.product.name,
                            "available_quantity": available,
                            "requested_quantity": item.quantity,
                            "message": (
                                f"Insufficient stock for {item.product.name}. "
                                f"Available: {available}, Requested: {item.quantity}"
                            ),
                        }
                    )

            if insufficient_stock:
                return Response(
                    {
                        "detail": "Insufficient stock for one or more products.",
                        "items": insufficient_stock,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            for item in order.items.all():
                inventory = inventory_map[item.product_id]
                inventory.available_quantity -= item.quantity
                inventory.save(update_fields=["available_quantity", "updated_at"])

            order.status = Order.Status.CONFIRMED
            order.save(update_fields=["status", "updated_at"])

        return Response(OrderSerializer(order, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        order = self.get_object()
        if order.status != Order.Status.CONFIRMED:
            return Response(
                {"detail": "Only confirmed orders can be marked as delivered."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = Order.Status.DELIVERED
        order.save(update_fields=["status", "updated_at"])
        return Response(OrderSerializer(order, context={"request": request}).data)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        aggregates = queryset.aggregate(
            total_orders=Count("id"),
            draft_orders=Count("id", filter=Q(status=Order.Status.DRAFT)),
            confirmed_orders=Count("id", filter=Q(status=Order.Status.CONFIRMED)),
            delivered_orders=Count("id", filter=Q(status=Order.Status.DELIVERED)),
            gross_order_value=Coalesce(
                Sum("total_amount"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            total_item_quantity=Coalesce(Sum("items__quantity"), Value(0)),
        )

        dealer_breakdown = list(
            queryset.values("dealer_id", "dealer__name")
            .annotate(
                order_count=Count("id"),
                total_amount=Coalesce(
                    Sum("total_amount"),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .order_by("dealer__name")
        )

        product_breakdown = list(
            queryset.values("items__product_id", "items__product__name", "items__product__sku")
            .annotate(
                total_quantity=Coalesce(Sum("items__quantity"), Value(0)),
                total_sales=Coalesce(
                    Sum("items__line_total"),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .exclude(items__product_id__isnull=True)
            .order_by("-total_quantity", "items__product__name")
        )

        response_data = {
            "filters": {
                "status": request.query_params.get("status"),
                "dealer": request.query_params.get("dealer"),
                "date_from": request.query_params.get("date_from"),
                "date_to": request.query_params.get("date_to"),
            },
            "summary": {
                "total_orders": aggregates["total_orders"],
                "draft_orders": aggregates["draft_orders"],
                "confirmed_orders": aggregates["confirmed_orders"],
                "delivered_orders": aggregates["delivered_orders"],
                "gross_order_value": str(aggregates["gross_order_value"]),
                "total_item_quantity": aggregates["total_item_quantity"],
            },
            "dealer_breakdown": [
                {
                    "dealer_id": item["dealer_id"],
                    "dealer_name": item["dealer__name"],
                    "order_count": item["order_count"],
                    "total_amount": str(item["total_amount"]),
                }
                for item in dealer_breakdown
            ],
            "product_breakdown": [
                {
                    "product_id": item["items__product_id"],
                    "product_name": item["items__product__name"],
                    "sku": item["items__product__sku"],
                    "total_quantity": item["total_quantity"],
                    "total_sales": str(item["total_sales"]),
                }
                for item in product_breakdown
            ],
        }
        return Response(response_data)


class InventoryViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = Inventory.objects.select_related("product").all()
    serializer_class = InventorySerializer
    lookup_field = "product_id"
    lookup_url_kwarg = "product_id"
    http_method_names = ["get", "put", "head", "options"]

    def update(self, request, *args, **kwargs):
        inventory = self.get_object()
        serializer = InventoryAdjustmentSerializer(data=request.data, context={"inventory": inventory})
        serializer.is_valid(raise_exception=True)
        inventory = serializer.save()
        return Response(InventorySerializer(inventory).data)
