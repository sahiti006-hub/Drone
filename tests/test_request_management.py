import pytest
import time
from app.models.user import User, UserRole
from app.models.delivery_request import (
    DeliveryRequest,
    RequestStatus,
    RequestPriority,
    EmergencyType,
    CargoCategory
)
from app.models.request_activity import RequestActivity
from app.services.delivery_service import DeliveryService
from app.extensions import db


@pytest.fixture
def test_users(app):
    with app.app_context():
        requester = User.query.filter_by(email="req.mgmt@example.com").first()
        if not requester:
            requester = User("Request Manager Requester", "req.mgmt@example.com", "Password123!", UserRole.REQUESTER.value)
            db.session.add(requester)

        operator = User.query.filter_by(email="op.mgmt@example.com").first()
        if not operator:
            operator = User("Request Manager Operator", "op.mgmt@example.com", "Password123!", UserRole.OPERATOR.value)
            db.session.add(operator)

        db.session.commit()
        return requester.id, operator.id


def test_request_creation_and_activity_logging(app, test_users):
    requester_id, _ = test_users
    with app.app_context():
        lat_offset = (time.time() % 100) / 1000.0
        req = DeliveryService.create_request(
            requester_id=requester_id,
            emergency_type="FOOD_GROCERIES",
            pickup_latitude=12.9000 + lat_offset,
            pickup_longitude=77.5000,
            destination_latitude=12.9500 + lat_offset,
            destination_longitude=77.5500,
            payload_weight_kg=2.5,
            priority="MEDIUM",
            custom_item_name="Prepared Nutrition Rations"
        )
        assert req is not None
        assert req.request_reference.startswith("REQ-")
        assert req.status == RequestStatus.PENDING.value

        # Check activity log
        activities = RequestActivity.query.filter_by(delivery_request_id=req.id).all()
        assert len(activities) >= 1
        assert activities[0].action == "REQUEST_SUBMITTED"
        assert activities[0].actor_id == requester_id


def test_request_idempotency_deduplication(app, test_users):
    requester_id, _ = test_users
    with app.app_context():
        pickup_lat = 12.8888
        pickup_lng = 77.4444
        dest_lat = 12.9999
        dest_lng = 77.5555

        req1 = DeliveryService.create_request(
            requester_id=requester_id,
            emergency_type="AGRICULTURE_RURAL",
            pickup_latitude=pickup_lat,
            pickup_longitude=pickup_lng,
            destination_latitude=dest_lat,
            destination_longitude=dest_lng,
            payload_weight_kg=1.0
        )

        # Immediate duplicate submission
        req2 = DeliveryService.create_request(
            requester_id=requester_id,
            emergency_type="AGRICULTURE_RURAL",
            pickup_latitude=pickup_lat,
            pickup_longitude=pickup_lng,
            destination_latitude=dest_lat,
            destination_longitude=dest_lng,
            payload_weight_kg=1.0
        )
        # Deduplication must return existing request
        assert req2.id == req1.id


def test_operator_approval_and_rejection_workflow(app, test_users):
    requester_id, operator_id = test_users
    with app.app_context():
        operator = db.session.get(User, operator_id)
        req = DeliveryService.create_request(
            requester_id=requester_id,
            emergency_type="ELECTRONICS_TECH",
            pickup_latitude=12.7777,
            pickup_longitude=77.3333,
            destination_latitude=12.8888,
            destination_longitude=77.4444,
            payload_weight_kg=1.5
        )

        # Operator approves
        approved_req = DeliveryService.approve_request(req.id, operator_user=operator, notes="Corridor clearance verified")
        assert approved_req.status == RequestStatus.APPROVED.value

        # Verify audit activity entry
        acts = RequestActivity.query.filter_by(delivery_request_id=req.id, action="REQUEST_APPROVED").all()
        assert len(acts) == 1
        assert acts[0].actor_id == operator_id

        # Create another for rejection
        req_to_reject = DeliveryService.create_request(
            requester_id=requester_id,
            emergency_type="CUSTOM_DELIVERY",
            pickup_latitude=12.6666,
            pickup_longitude=77.2222,
            destination_latitude=12.7777,
            destination_longitude=77.3333,
            payload_weight_kg=2.0
        )
        rejected_req = DeliveryService.reject_request(
            req_to_reject.id,
            operator_user=operator,
            reason="Flight corridor crosses active temporary flight restriction (TFR)"
        )
        assert rejected_req.status == RequestStatus.REJECTED.value
        assert rejected_req.rejection_reason is not None


def test_delivery_completion_lifecycle(app, test_users):
    requester_id, operator_id = test_users
    with app.app_context():
        operator = db.session.get(User, operator_id)
        req = DeliveryService.create_request(
            requester_id=requester_id,
            emergency_type="PERSONAL_HOUSEHOLD",
            pickup_latitude=12.5555,
            pickup_longitude=77.1111,
            destination_latitude=12.6666,
            destination_longitude=77.2222,
            payload_weight_kg=0.8
        )
        req.status = RequestStatus.IN_TRANSIT.value
        db.session.commit()

        completed_req = DeliveryService.complete_delivery(req.id, operator_user=operator)
        assert completed_req.status == RequestStatus.DELIVERED.value


def test_request_filtering_and_pagination(app, test_users):
    requester_id, _ = test_users
    with app.app_context():
        requester = db.session.get(User, requester_id)
        pagination = DeliveryService.get_requests_for_user(
            user=requester,
            emergency_type="FOOD_GROCERIES",
            page=1,
            per_page=10
        )
        assert pagination is not None
        assert hasattr(pagination, "items")
        for item in pagination.items:
            assert item.cargo_category == "FOOD_GROCERIES" or item.emergency_type == "FOOD_GROCERIES"
