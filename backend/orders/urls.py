from rest_framework.routers import DefaultRouter

from .views import DealerViewSet, InventoryViewSet, OrderViewSet, ProductViewSet

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("dealers", DealerViewSet, basename="dealer")
router.register("orders", OrderViewSet, basename="order")
router.register("inventory", InventoryViewSet, basename="inventory")

urlpatterns = router.urls
