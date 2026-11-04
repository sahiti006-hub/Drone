from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Dict, Any
from app.extensions import db
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
    CargoCategory,
    CARGO_CATEGORY_REGISTRY,
    LEGACY_CATEGORY_MAP,
    normalize_cargo_category,
)
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.request_activity import RequestActivity


class DeliveryServiceError(Exception):
    """Base exception for delivery request business logic errors."""
    pass


class DeliveryRequestNotFoundError(DeliveryServiceError):
    """Raised when the specified delivery request is not found."""
    pass


class InvalidRequestStateError(DeliveryServiceError):
    """Raised when an action is prohibited for the request's current lifecycle state."""
    pass


class DeliveryPermissionDeniedError(DeliveryServiceError):
    """Raised when a user attempts to access or modify an unauthorized delivery request."""
    pass


class DeliveryService:
    """Service layer governing universal multipurpose delivery requests, lifecycle state machine, and RBAC."""

    @staticmethod
    def get_supported_categories() -> set[str]:
        """Aggregate set of all supported category codes and legacy aliases."""
        return (
            {e.value for e in EmergencyType}
            | {c.value for c in CargoCategory}
            | set(CARGO_CATEGORY_REGISTRY.keys())
            | set(LEGACY_CATEGORY_MAP.keys())
        )

    @staticmethod
    def create_request(
        requester_id: int,
        emergency_type: str,
        pickup_latitude: float,
        pickup_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        payload_weight_kg: float,
        priority: str = RequestPriority.HIGH.value,
        description: str = None,
        delivery_direction: str = "SEND",
        custom_item_name: str = None,
        package_dimensions: str = None,
        package_count: int = 1,
        handling_instructions: str = None,
        pickup_contact_name: str = None,
        pickup_contact_phone: str = None,
        delivery_contact_name: str = None,
        delivery_contact_phone: str = None,
        special_instructions: str = None,
        idempotency_key: str = None,
    ) -> DeliveryRequest:
        """Create and persist a new multipurpose delivery request with strict validation and audit tracking."""
        # 1. Validate Requester
        requester = db.session.get(User, requester_id)
        if not requester or not requester.is_active:
            raise DeliveryServiceError(f"Valid active requester ID {requester_id} is required.")

        # 2. Validate Category
        supported_types = DeliveryService.get_supported_categories()
        clean_type = str(emergency_type).strip().upper()
        if clean_type not in supported_types:
            raise ValueError(f"Unsupported delivery category '{emergency_type}'.")

        supported_priorities = {p.value for p in RequestPriority}
        clean_priority = str(priority).strip().upper()
        if clean_priority not in supported_priorities:
            raise ValueError(f"Unsupported priority '{priority}'. Allowed: {sorted(supported_priorities)}")

        # 3. Enforce Cargo Category Weight Limits
        norm_cat = normalize_cargo_category(clean_type)
        cat_meta = CARGO_CATEGORY_REGISTRY.get(norm_cat)
        if cat_meta and float(payload_weight_kg) > cat_meta["max_weight_kg"]:
            raise ValueError(
                f"Weight {payload_weight_kg} kg exceeds maximum permitted payload of {cat_meta['max_weight_kg']} kg "
                f"for category '{cat_meta['name']}'."
            )

        # 4. Idempotency Check: Prevent duplicate submissions within 10 seconds
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=10)
        recent_duplicate = DeliveryRequest.query.filter(
            DeliveryRequest.requester_id == requester.id,
            DeliveryRequest.pickup_latitude == pickup_latitude,
            DeliveryRequest.pickup_longitude == pickup_longitude,
            DeliveryRequest.destination_latitude == destination_latitude,
            DeliveryRequest.destination_longitude == destination_longitude,
            DeliveryRequest.created_at >= cutoff,
        ).first()

        if recent_duplicate:
            return recent_duplicate

        # 5. Create Model
        req = DeliveryRequest(
            requester_id=requester.id,
            emergency_type=clean_type,
            pickup_latitude=pickup_latitude,
            pickup_longitude=pickup_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
            payload_weight_kg=payload_weight_kg,
            priority=clean_priority,
            status=RequestStatus.PENDING.value,
            description=description,
            delivery_direction=delivery_direction or "SEND",
            custom_item_name=custom_item_name,
            package_dimensions=package_dimensions,
            package_count=package_count or 1,
            handling_instructions=handling_instructions,
            pickup_contact_name=pickup_contact_name,
            pickup_contact_phone=pickup_contact_phone,
            delivery_contact_name=delivery_contact_name,
            delivery_contact_phone=delivery_contact_phone,
            special_instructions=special_instructions,
        )

        db.session.add(req)
        db.session.flush()

        # 6. Record Initial Audit Activity
        db.session.add(RequestActivity(
            delivery_request_id=req.id,
            actor_id=requester.id,
            actor_role=requester.role,
            from_status=None,
            to_status=req.status,
            action="REQUEST_SUBMITTED",
            reason="User registered new multipurpose delivery request.",
            metadata={
                "category": req.emergency_type,
                "weight_kg": float(req.payload_weight_kg),
                "direction": req.delivery_direction,
                "priority": req.priority,
            },
        ))

        db.session.commit()
        return req

    @staticmethod
    def get_requests_for_user(
        user: User,
        priority: str = None,
        status: str = None,
        emergency_type: str = None,
        delivery_direction: str = None,
        search_query: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        page: int = None,
        per_page: int = 15,
    ) -> Any:
        """Fetch delivery requests filtered by criteria and strictly scoped by user role.

        - REQUESTER: Sees ONLY their own requests.
        - OPERATOR & ADMIN: Sees all requests across the system.
        """
        query = DeliveryRequest.query

        # RBAC Scoping
        if user.role == UserRole.REQUESTER.value:
            query = query.filter(DeliveryRequest.requester_id == user.id)

        # Filters
        if priority and priority != "ALL":
            query = query.filter(DeliveryRequest.priority == str(priority).upper())

        if status and status != "ALL":
            query = query.filter(DeliveryRequest.status == str(status).upper())

        if emergency_type and emergency_type != "ALL":
            clean_et = str(emergency_type).strip().upper()
            norm = normalize_cargo_category(clean_et)
            # Match either exact code or normalized code or legacy alias
            query = query.filter(
                (DeliveryRequest.emergency_type == clean_et) |
                (DeliveryRequest.emergency_type == norm)
            )

        if delivery_direction and delivery_direction != "ALL":
            query = query.filter(DeliveryRequest.delivery_direction == str(delivery_direction).upper())

        if search_query:
            term = f"%{search_query.strip()}%"
            query = query.filter(
                (DeliveryRequest.description.ilike(term)) |
                (DeliveryRequest.custom_item_name.ilike(term)) |
                (DeliveryRequest.request_reference.ilike(term)) |
                (DeliveryRequest.pickup_contact_name.ilike(term)) |
                (DeliveryRequest.delivery_contact_name.ilike(term))
            )

        if start_date:
            query = query.filter(DeliveryRequest.created_at >= start_date)

        if end_date:
            query = query.filter(DeliveryRequest.created_at <= end_date)

        query = query.order_by(DeliveryRequest.created_at.desc())

        if page is not None:
            return query.paginate(page=page, per_page=per_page, error_out=False)

        return query.all()

    @staticmethod
    def get_request_by_id(request_id: int, user: User = None) -> DeliveryRequest:
        """Fetch a single delivery request by ID with IDOR authorization checking."""
        req = db.session.get(DeliveryRequest, request_id)
        if not req:
            raise DeliveryRequestNotFoundError(f"Delivery request #{request_id} does not exist.")

        # IDOR Guard
        if user and user.role == UserRole.REQUESTER.value and req.requester_id != user.id:
            raise DeliveryPermissionDeniedError(
                f"User {user.email} is not authorized to inspect delivery request #{request_id}."
            )

        return req

    @staticmethod
    def update_request(
        request_id: int,
        user: User,
        emergency_type: str = None,
        priority: str = None,
        payload_weight_kg: float = None,
        description: str = None,
        pickup_latitude: float = None,
        pickup_longitude: float = None,
        destination_latitude: float = None,
        destination_longitude: float = None,
        custom_item_name: str = None,
        handling_instructions: str = None,
        special_instructions: str = None,
    ) -> DeliveryRequest:
        """Update editable fields of a delivery request before mission dispatch."""
        req = DeliveryService.get_request_by_id(request_id, user=user)

        if req.status not in {RequestStatus.PENDING.value, RequestStatus.ROUTE_CALCULATED.value, RequestStatus.SUBMITTED.value}:
            raise InvalidRequestStateError(
                f"Cannot modify request #{req.id}: current state is '{req.status}'. "
                f"Modifications are allowed only before drone assignment."
            )

        if emergency_type:
            supported = DeliveryService.get_supported_categories()
            clean_type = str(emergency_type).strip().upper()
            if clean_type not in supported:
                raise ValueError(f"Unsupported delivery category: {emergency_type}")
            req.emergency_type = clean_type

        if priority:
            supported_priorities = {p.value for p in RequestPriority}
            clean_priority = str(priority).strip().upper()
            if clean_priority not in supported_priorities:
                raise ValueError(f"Unsupported priority: {priority}")
            req.priority = clean_priority

        if payload_weight_kg is not None:
            if float(payload_weight_kg) <= 0:
                raise ValueError("Payload weight must be strictly positive.")
            req.payload_weight_kg = payload_weight_kg

        if description is not None:
            req.description = description.strip() or None

        if custom_item_name is not None:
            req.custom_item_name = custom_item_name.strip() or None

        if handling_instructions is not None:
            req.handling_instructions = handling_instructions.strip() or None

        if special_instructions is not None:
            req.special_instructions = special_instructions.strip() or None

        if pickup_latitude is not None and pickup_longitude is not None:
            DeliveryRequest.validate_coordinates(pickup_latitude, pickup_longitude, "Pickup")
            req.pickup_latitude = pickup_latitude
            req.pickup_longitude = pickup_longitude

        if destination_latitude is not None and destination_longitude is not None:
            DeliveryRequest.validate_coordinates(destination_latitude, destination_longitude, "Destination")
            req.destination_latitude = destination_latitude
            req.destination_longitude = destination_longitude

        db.session.add(RequestActivity(
            delivery_request_id=req.id,
            actor_id=user.id,
            actor_role=user.role,
            from_status=req.status,
            to_status=req.status,
            action="REQUEST_UPDATED",
            reason="User updated request details.",
        ))

        db.session.commit()
        return req

    @staticmethod
    def approve_request(request_id: int, operator_user: User, notes: str = None) -> DeliveryRequest:
        """Operator/Admin approval of a pending delivery request."""
        if operator_user.role not in (UserRole.ADMIN.value, UserRole.OPERATOR.value):
            raise DeliveryPermissionDeniedError("Only Operators and Administrators can approve requests.")

        req = DeliveryService.get_request_by_id(request_id)
        if req.status in {RequestStatus.CANCELLED.value, RequestStatus.REJECTED.value, RequestStatus.DELIVERED.value}:
            raise InvalidRequestStateError(f"Cannot approve request in '{req.status}' state.")

        prev_status = req.status
        req.status = RequestStatus.APPROVED.value

        db.session.add(RequestActivity(
            delivery_request_id=req.id,
            actor_id=operator_user.id,
            actor_role=operator_user.role,
            from_status=prev_status,
            to_status=req.status,
            action="REQUEST_APPROVED",
            reason=notes or "Operator approved request for flight corridor assignment.",
        ))

        db.session.commit()
        return req

    @staticmethod
    def reject_request(request_id: int, operator_user: User, reason: str) -> DeliveryRequest:
        """Operator/Admin rejection of an infeasible or non-compliant delivery request."""
        if operator_user.role not in (UserRole.ADMIN.value, UserRole.OPERATOR.value):
            raise DeliveryPermissionDeniedError("Only Operators and Administrators can reject requests.")

        req = DeliveryService.get_request_by_id(request_id)
        if req.status in {RequestStatus.DELIVERED.value, RequestStatus.CANCELLED.value}:
            raise InvalidRequestStateError(f"Cannot reject request in '{req.status}' state.")

        prev_status = req.status
        req.status = RequestStatus.REJECTED.value
        req.rejection_reason = reason or "Rejected due to operational or regulatory constraints."

        db.session.add(RequestActivity(
            delivery_request_id=req.id,
            actor_id=operator_user.id,
            actor_role=operator_user.role,
            from_status=prev_status,
            to_status=req.status,
            action="REQUEST_REJECTED",
            reason=req.rejection_reason,
        ))

        db.session.commit()
        return req

    @staticmethod
    def complete_delivery(request_id: int, operator_user: User) -> DeliveryRequest:
        """Operator or System marks delivery as successfully delivered after drone arrival."""
        if operator_user.role not in (UserRole.ADMIN.value, UserRole.OPERATOR.value):
            raise DeliveryPermissionDeniedError("Only Operators and Administrators can complete requests.")

        req = DeliveryService.get_request_by_id(request_id)
        prev_status = req.status
        req.status = RequestStatus.DELIVERED.value

        # Close any active assignment
        active_assign = DroneAssignment.query.filter_by(
            delivery_request_id=req.id,
            status=AssignmentStatus.ACTIVE.value,
        ).first()
        if active_assign:
            active_assign.status = AssignmentStatus.COMPLETED.value
            if active_assign.drone:
                active_assign.drone.status = DroneStatus.AVAILABLE.value

        db.session.add(RequestActivity(
            delivery_request_id=req.id,
            actor_id=operator_user.id,
            actor_role=operator_user.role,
            from_status=prev_status,
            to_status=req.status,
            action="DELIVERY_COMPLETED",
            reason="Operator confirmed cargo delivery at destination.",
        ))

        db.session.commit()
        return req

    @staticmethod
    def cancel_request(request_id: int, user: User, reason: str = None) -> DeliveryRequest:
        """Cancel a delivery request conforming to state transition rules."""
        req = DeliveryService.get_request_by_id(request_id, user=user)

        if req.status == RequestStatus.DELIVERED.value:
            raise InvalidRequestStateError(f"Cannot cancel request #{req.id}: delivery is already COMPLETED.")

        if req.status == RequestStatus.CANCELLED.value:
            return req

        # Check if an active drone assignment exists
        active_assignment = DroneAssignment.query.filter_by(
            delivery_request_id=req.id,
            status=AssignmentStatus.ACTIVE.value,
        ).first()

        if active_assignment:
            if user.role == UserRole.REQUESTER.value:
                raise InvalidRequestStateError(
                    f"Mission is already dispatched with Drone {active_assignment.drone.drone_code}. "
                    f"Please contact an emergency fleet operator to abort the flight."
                )

            from app.services.assignment_service import AssignmentService
            AssignmentService.abort_assignment(
                active_assignment.id,
                reason=reason or f"Cancelled by {user.role}: {user.full_name}",
            )

        prev_status = req.status
        req.status = RequestStatus.CANCELLED.value
        if reason:
            existing_desc = req.description or ""
            req.description = f"{existing_desc} [Cancellation Reason: {reason}]".strip()

        db.session.add(RequestActivity(
            delivery_request_id=req.id,
            actor_id=user.id,
            actor_role=user.role,
            from_status=prev_status,
            to_status=req.status,
            action="REQUEST_CANCELLED",
            reason=reason or "Cancelled by user or operator.",
        ))

        db.session.commit()
        return req
