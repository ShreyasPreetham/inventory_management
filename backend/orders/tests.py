from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from .models import Dealer, Order, OrderItem, Product


class OrderWorkflowAPITests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="BP-001",
            name="Brake Pad",
            unit_price=Decimal("500.00"),
        )
        self.product.inventory.available_quantity = 100
        self.product.inventory.save()

        self.second_product = Product.objects.create(
            sku="OC-001",
            name="Oil Can",
            unit_price=Decimal("250.00"),
        )
        self.second_product.inventory.available_quantity = 5
        self.second_product.inventory.save()

        self.dealer = Dealer.objects.create(
            code="ABC001",
            name="ABC Motors",
            email="abc@example.com",
            phone="9999999999",
        )

    def create_draft_order(self, items):
        response = self.client.post(
            "/api/orders/",
            {
                "dealer": self.dealer.id,
                "items": items,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def test_successful_order_flow_deducts_stock_and_delivers(self):
        order = self.create_draft_order(
            [{"product_id": self.product.id, "quantity": 10}]
        )

        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.available_quantity, 100)
        self.assertEqual(order["status"], Order.Status.DRAFT)
        self.assertEqual(order["total_amount"], "5000.00")

        confirm_response = self.client.post(f"/api/orders/{order['id']}/confirm/")
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)

        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.available_quantity, 90)
        self.assertEqual(confirm_response.json()["status"], Order.Status.CONFIRMED)

        deliver_response = self.client.post(f"/api/orders/{order['id']}/deliver/")
        self.assertEqual(deliver_response.status_code, status.HTTP_200_OK)
        self.assertEqual(deliver_response.json()["status"], Order.Status.DELIVERED)

    def test_confirm_rejects_entire_order_when_any_item_has_insufficient_stock(self):
        order = self.create_draft_order(
            [
                {"product_id": self.product.id, "quantity": 2},
                {"product_id": self.second_product.id, "quantity": 10},
            ]
        )

        confirm_response = self.client.post(f"/api/orders/{order['id']}/confirm/")
        self.assertEqual(confirm_response.status_code, status.HTTP_400_BAD_REQUEST)

        payload = confirm_response.json()
        self.assertEqual(payload["detail"], "Insufficient stock for one or more products.")
        self.assertEqual(payload["items"][0]["available_quantity"], 5)
        self.assertEqual(payload["items"][0]["requested_quantity"], 10)
        self.assertIn("Insufficient stock for Oil Can", payload["items"][0]["message"])

        self.product.inventory.refresh_from_db()
        self.second_product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.available_quantity, 100)
        self.assertEqual(self.second_product.inventory.available_quantity, 5)

    def test_confirmed_order_cannot_be_edited(self):
        order = self.create_draft_order(
            [{"product_id": self.product.id, "quantity": 1}]
        )
        confirm_response = self.client.post(f"/api/orders/{order['id']}/confirm/")
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)

        update_response = self.client.put(
            f"/api/orders/{order['id']}/",
            {
                "dealer": self.dealer.id,
                "items": [{"product_id": self.product.id, "quantity": 3}],
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only draft orders can be modified.", str(update_response.json()))

    def test_deliver_rejects_draft_order(self):
        order = self.create_draft_order(
            [{"product_id": self.product.id, "quantity": 1}]
        )

        deliver_response = self.client.post(f"/api/orders/{order['id']}/deliver/")
        self.assertEqual(deliver_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            deliver_response.json()["detail"],
            "Only confirmed orders can be marked as delivered.",
        )

    def test_deleting_confirmed_order_restores_stock(self):
        order = self.create_draft_order(
            [{"product_id": self.product.id, "quantity": 10}]
        )
        confirm_response = self.client.post(f"/api/orders/{order['id']}/confirm/")
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)

        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.available_quantity, 90)

        delete_response = self.client.delete(f"/api/orders/{order['id']}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.available_quantity, 100)
        self.assertFalse(Order.objects.filter(id=order["id"]).exists())

    def test_delivered_order_cannot_be_deleted(self):
        order = self.create_draft_order(
            [{"product_id": self.product.id, "quantity": 10}]
        )
        self.client.post(f"/api/orders/{order['id']}/confirm/")
        deliver_response = self.client.post(f"/api/orders/{order['id']}/deliver/")
        self.assertEqual(deliver_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(f"/api/orders/{order['id']}/")
        self.assertEqual(delete_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            delete_response.json()["detail"],
            "Delivered orders cannot be deleted.",
        )

    def test_inventory_adjustment_prevents_negative_stock(self):
        response = self.client.put(
            f"/api/inventory/{self.second_product.id}/",
            {"adjustment_quantity": -10, "updated_by": "admin"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cannot reduce stock below zero", str(response.json()))

    def test_inventory_adjustment_applies_delta_and_audit_field(self):
        response = self.client.put(
            f"/api/inventory/{self.product.id}/",
            {"adjustment_quantity": 25, "updated_by": "admin.user"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["available_quantity"], 125)
        self.assertEqual(response.json()["last_updated_by"], "admin.user")

    def test_product_gets_inventory_record_on_creation(self):
        product = Product.objects.create(
            sku="FL-001",
            name="Fuel Line",
            unit_price=Decimal("100.00"),
        )
        self.assertEqual(product.inventory.available_quantity, 0)

    def test_duplicate_products_in_same_order_are_rejected(self):
        response = self.client.post(
            "/api/orders/",
            {
                "dealer": self.dealer.id,
                "items": [
                    {"product_id": self.product.id, "quantity": 1},
                    {"product_id": self.product.id, "quantity": 2},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Duplicate product", str(response.json()))

    def test_order_filters_by_status(self):
        draft_order = self.create_draft_order(
            [{"product_id": self.product.id, "quantity": 1}]
        )
        confirmed_order = self.create_draft_order(
            [{"product_id": self.second_product.id, "quantity": 1}]
        )
        self.client.post(f"/api/orders/{confirmed_order['id']}/confirm/")

        response = self.client.get("/api/orders/?status=confirmed")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        order_ids = {item["id"] for item in response.json()}
        self.assertIn(confirmed_order["id"], order_ids)
        self.assertNotIn(draft_order["id"], order_ids)

    def test_order_summary_endpoint_returns_aggregated_report(self):
        draft_order = self.create_draft_order(
            [{"product_id": self.product.id, "quantity": 2}]
        )
        confirmed_order = self.create_draft_order(
            [{"product_id": self.second_product.id, "quantity": 1}]
        )
        self.client.post(f"/api/orders/{confirmed_order['id']}/confirm/")

        response = self.client.get("/api/orders/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payload = response.json()
        self.assertEqual(payload["summary"]["total_orders"], 2)
        self.assertEqual(payload["summary"]["draft_orders"], 1)
        self.assertEqual(payload["summary"]["confirmed_orders"], 1)
        self.assertEqual(payload["summary"]["delivered_orders"], 0)
        self.assertEqual(payload["summary"]["gross_order_value"], "1250.00")
        self.assertEqual(payload["summary"]["total_item_quantity"], 3)

        filtered_response = self.client.get("/api/orders/summary/?status=confirmed")
        self.assertEqual(filtered_response.status_code, status.HTTP_200_OK)
        filtered_payload = filtered_response.json()
        self.assertEqual(filtered_payload["summary"]["total_orders"], 1)
        self.assertEqual(filtered_payload["summary"]["confirmed_orders"], 1)
        self.assertEqual(filtered_payload["summary"]["gross_order_value"], "250.00")

    def test_dealer_phone_must_be_exactly_ten_digits(self):
        response = self.client.post(
            "/api/dealers/",
            {
                "code": "XYZ001",
                "name": "XYZ Motors",
                "email": "xyz@example.com",
                "phone": "8888888971110987",
                "address": "Pune",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("exactly 10 digits", str(response.json()))

    def test_dealer_email_is_normalized_to_lowercase(self):
        response = self.client.post(
            "/api/dealers/",
            {
                "code": "XYZ002",
                "name": "XYZ Motors 2",
                "email": "XYZ@GMAIL.COM",
                "phone": "8888888971",
                "address": "Pune",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["email"], "xyz@gmail.com")

    def test_dealer_email_must_end_with_gmail(self):
        response = self.client.post(
            "/api/dealers/",
            {
                "code": "XYZ003",
                "name": "XYZ Motors 3",
                "email": "xyz@yahoo.com",
                "phone": "8888888971",
                "address": "Pune",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("@gmail.com", str(response.json()))
