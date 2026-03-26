from django.contrib import admin

from .models import Dealer, Inventory, Order, OrderItem, Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "unit_price", "is_active", "created_at")
    search_fields = ("sku", "name")
    list_filter = ("is_active",)


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ("product", "available_quantity", "last_updated_by", "updated_at")
    search_fields = ("product__sku", "product__name")


@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "email", "phone", "is_active")
    search_fields = ("code", "name", "email")
    list_filter = ("is_active",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("line_total",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "dealer", "status", "total_amount", "created_at")
    search_fields = ("order_number", "dealer__name", "dealer__code")
    list_filter = ("status", "created_at")
    inlines = [OrderItemInline]

# Register your models here.
