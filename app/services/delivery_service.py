from datetime import datetime, timezone
from app.extensions import db
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
)
from app.models.user import User, UserRole
from app.models.drone_assignment import DroneAssignment, AssignmentStatus


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
    """Service layer governing delivery request creation, validation, lifecycle, and RBAC."""

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
    ) -> DeliveryRequest:
        """Create and persist a new emergency delivery request with strict server-side validation."""
        # 1. Validate Requester
        requester = db.session.get(User, requester_id)
        if not requester or not requester.is_active:
            raise DeliveryServiceError(f"Valid active requester ID {requester_id} is required.")

        # 2. Validate Enums
        supported_types = {e.value for e in EmergencyType}
        clean_type = str(emergency_type).strip().upper()
        if clean_type not in supported_types:
            raise ValueError(f"Unsupported emergency type '{emergency_type}'. Allowed: {sorted(supported_types)}")

        supported_priorities = {p.value for p in RequestPriority}
        clean_priority = str(priority).strip().upper()
        if clean_priority not in supported_priorities:
            raise ValueError(f"Unsupported priority '{priority}'. Allowed: {sorted(supported_priorities)}")

        # 3. Create Model (Coordinates & weight are validated by DeliveryRequest.__init__)
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
        )

        db.session.add(req)
        db.session.commit()
        return req

    @staticmethod
    def get_requests_for_user(
        user: User,
        priority: str = None,
        status: str = None,
        emergency_type: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list[DeliveryRequest]:
        """Fetch delivery requests filtered by criteria and strictly scoped by user role.

        - REQUESTER: Sees ONLY their own requests.
        - OPERATOR & ADMIN: Sees all requests across the system.
        """
        query = DeliveryRequest.query

        # RBAC Scoping
        if user.role == UserRole.REQUESTER.value:
            query = query.filter(DeliveryRequest.requester_id == user.id)

        # Filters
        if priority:
            query = query.filter(DeliveryRequest.priority == str(priority).upper())

        if status:
            query = query.filter(DeliveryRequest.status == str(status).upper())

        if emergency_type:
            query = query.filter(DeliveryRequest.emergency_type == str(emergency_type).upper())

        if start_date:
            query = query.filter(DeliveryRequest.created_at >= start_date)

        if end_date:
            query = query.filter(DeliveryRequest.created_at <= end_date)

        return query.order_by(DeliveryRequest.created_at.desc()).all()

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
    ) -> DeliveryRequest:
        """Update editable fields of a delivery request.

        Modification is permitted only while the request is PENDING or ROUTE_CALCULATED.
        Once ASSIGNED, IN_TRANSIT, or DELIVERED, modification is prohibited.
        """
        req = DeliveryService.get_request_by_id(request_id, user=user)

        if req.status not in {RequestStatus.PENDING.value, RequestStatus.ROUTE_CALCULATED.value}:
            raise InvalidRequestStateError(
                f"Cannot modify request #{req.id}: current state is '{req.status}'. "
                f"Modifications are allowed only before drone assignment."
            )

        if emergency_type:
            supported_types = {e.value for e in EmergencyType}
            clean_type = str(emergency_type).strip().upper()
            if clean_type not in supported_types:
                raise ValueError(f"Unsupported emergency type: {emergency_type}")
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

        if pickup_latitude is not None and pickup_longitude is not None:
            DeliveryRequest.validate_coordinates(pickup_latitude, pickup_longitude, "Pickup")
            req.pickup_latitude = pickup_latitude
            req.pickup_longitude = pickup_longitude

        if destination_latitude is not None and destination_longitude is not None:
            DeliveryRequest.validate_coordinates(destination_latitude, destination_longitude, "Destination")
            req.destination_latitude = destination_latitude
            req.destination_longitude = destination_longitude

        db.session.commit()
        return req

    @staticmethod
    def cancel_request(request_id: int, user: User, reason: str = None) -> DeliveryRequest:
        """Cancel a delivery request conforming to state transition rules.

        - PENDING or ROUTE_CALCULATED: Can be cancelled directly.
        - ASSIGNED or IN_TRANSIT: Can be aborted/cancelled by OPERATOR or ADMIN; releases active drone.
        - DELIVERED: Cannot be cancelled.
        - CANCELLED: Already cancelled.
        """
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
            # Requesters cannot unilaterally cancel missions already in the air
            if user.role == UserRole.REQUESTER.value:
                raise InvalidRequestStateError(
                    f"Mission is already dispatched with Drone {active_assignment.drone.drone_code}. "
                    f"Please contact an emergency fleet operator to abort the flight."
                )

            # Operator or Admin aborts the mission and returns drone to available
            from app.services.assignment_service import AssignmentService
            AssignmentService.abort_assignment(
                active_assignment.id,
                reason=reason or f"Cancelled by {user.role}: {user.full_name}",
            )

        req.status = RequestStatus.CANCELLED.value
        if reason:
            existing_desc = req.description or ""
            req.description = f"{existing_desc} [Cancellation Reason: {reason}]".strip()

        db.session.commit()
        return req
