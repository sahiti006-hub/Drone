"""Simulated payment gateway, financial transaction ledger, and refund engine."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import uuid
from typing import Dict, Any, Optional
from app.extensions import db
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.payment_transaction import (
    PaymentTransaction,
    PaymentStatus,
    PaymentMethod,
    RefundTransaction,
)
from app.models.drone import Drone, DroneStatus
from app.services.notification_service import NotificationService


class PaymentServiceError(Exception):
    """Base exception for payment operations."""
    pass


class DuplicateTransactionError(PaymentServiceError):
    """Raised when duplicate non-idempotent payment is attempted."""
    pass


class InvalidPaymentStateError(PaymentServiceError):
    """Raised when payment is processed for invalid booking state."""
    pass


class PaymentService:
    """Manages simulated cashless transactions, idempotent processing, and refund policies."""

    @classmethod
    def process_payment(
        cls,
        booking_id: int,
        payment_method: str = PaymentMethod.SIMULATED_UPI.value,
        idempotency_key: Optional[str] = None,
        simulate_failure: bool = False,
    ) -> PaymentTransaction:
        """Process simulated cashless payment for a confirmed drone booking."""
        booking = db.session.get(DroneBooking, booking_id)
        if not booking:
            raise PaymentServiceError(f"Booking #{booking_id} not found.")

        # Check existing idempotency key to prevent double charging
        idem_key = idempotency_key or f"IDEM-{booking.id}-{uuid.uuid4().hex[:8]}"
        existing_txn = PaymentTransaction.query.filter_by(idempotency_key=idem_key).first()
        if existing_txn:
            return existing_txn

        # Cannot pay for already paid or cancelled bookings
        if booking.status in (BookingStatus.PAID.value, BookingStatus.DISPATCHED.value, BookingStatus.DELIVERED.value):
            raise InvalidPaymentStateError(f"Booking #{booking.booking_reference} is already paid or active.")

        if booking.status in (BookingStatus.CANCELLED.value, BookingStatus.WEATHER_BLOCKED.value):
            raise InvalidPaymentStateError(
                f"Cannot process payment for booking with status '{booking.status}'."
            )

        now = datetime.now(timezone.utc)
        quoted_amt = Decimal(str(booking.accepted_price))
        final_amt = Decimal(str(booking.final_price))

        txn = PaymentTransaction(
            transaction_reference=f"TXN-{uuid.uuid4().hex[:12].upper()}",
            idempotency_key=idem_key,
            booking_id=booking.id,
            delivery_request_id=booking.delivery_request_id,
            requester_id=booking.requester_id,
            quoted_amount=quoted_amt,
            final_amount=final_amt,
            refund_amount=Decimal("0.00"),
            payment_method=payment_method,
            payment_status=PaymentStatus.PENDING.value,
        )
        db.session.add(txn)
        db.session.flush()

        if simulate_failure:
            txn.payment_status = PaymentStatus.FAILED.value
            txn.gateway_response_code = "SIMULATED_INSUFFICIENT_FUNDS"
            txn.reason_for_adjustment = "Simulated bank gateway decline."
            db.session.commit()

            NotificationService.create_notification(
                user_id=booking.requester_id,
                booking_id=booking.id,
                delivery_request_id=booking.delivery_request_id,
                notification_type="PAYMENT_FAILURE",
                title="Payment Failed",
                message=f"Simulated payment for {booking.booking_reference} failed: Bank gateway declined transaction.",
                severity="DANGER",
            )
            return txn

        # Successful payment flow
        txn.payment_status = PaymentStatus.PAID.value
        txn.gateway_response_code = "SIMULATED_SUCCESS_AUTH"
        txn.paid_at = now
        booking.status = BookingStatus.PAID.value

        db.session.commit()

        NotificationService.create_notification(
            user_id=booking.requester_id,
            booking_id=booking.id,
            delivery_request_id=booking.delivery_request_id,
            notification_type="PAYMENT_SUCCESS",
            title="Payment Successful",
            message=f"₹{float(final_amt):.2f} processed successfully via {payment_method}. Txn Ref: {txn.transaction_reference}.",
            severity="SUCCESS",
        )

        return txn

    @classmethod
    def process_refund(
        cls,
        booking_id: int,
        amount: Optional[Decimal] = None,
        reason: str = "Mission cancellation",
        refund_type: str = "FULL",
    ) -> RefundTransaction:
        """Process simulated full or partial refund for a booking."""
        booking = db.session.get(DroneBooking, booking_id)
        if not booking:
            raise PaymentServiceError(f"Booking #{booking_id} not found.")

        # Find successful payment transaction
        payment_txn = PaymentTransaction.query.filter_by(
            booking_id=booking.id,
            payment_status=PaymentStatus.PAID.value,
        ).first()

        if not payment_txn:
            # Check partially refunded
            payment_txn = PaymentTransaction.query.filter_by(
                booking_id=booking.id,
                payment_status=PaymentStatus.PARTIALLY_REFUNDED.value,
            ).first()

        if not payment_txn:
            raise PaymentServiceError(f"No paid transaction found for booking #{booking.booking_reference}.")

        paid_amount = Decimal(str(payment_txn.final_amount))
        current_refunded = Decimal(str(payment_txn.refund_amount))
        max_refundable = paid_amount - current_refunded

        if max_refundable <= Decimal("0.00"):
            raise PaymentServiceError(f"Booking #{booking.booking_reference} has already been fully refunded.")

        refund_amt = Decimal(str(amount)) if amount is not None else max_refundable
        refund_amt = min(refund_amt, max_refundable).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        new_total_refunded = current_refunded + refund_amt
        payment_txn.refund_amount = new_total_refunded
        payment_txn.refunded_at = datetime.now(timezone.utc)

        if new_total_refunded >= paid_amount:
            payment_txn.payment_status = PaymentStatus.REFUNDED.value
        else:
            payment_txn.payment_status = PaymentStatus.PARTIALLY_REFUNDED.value

        refund = RefundTransaction(
            refund_reference=f"REF-{uuid.uuid4().hex[:12].upper()}",
            payment_transaction_id=payment_txn.id,
            booking_id=booking.id,
            amount=refund_amt,
            refund_type=refund_type,
            reason=reason,
            status="COMPLETED",
        )
        db.session.add(refund)

        # Release drone back to AVAILABLE if not already available
        drone = db.session.get(Drone, booking.drone_id)
        if drone and drone.status in (DroneStatus.RESERVED.value, DroneStatus.IN_TRANSIT.value):
            drone.status = DroneStatus.AVAILABLE.value

        # Update booking status
        if refund_type == "WEATHER_CANCEL":
            booking.status = BookingStatus.WEATHER_BLOCKED.value
        elif refund_type == "DIVERSION_COMPENSATION":
            booking.status = BookingStatus.DIVERTED.value
        else:
            booking.status = BookingStatus.CANCELLED.value

        db.session.commit()

        NotificationService.create_notification(
            user_id=booking.requester_id,
            booking_id=booking.id,
            delivery_request_id=booking.delivery_request_id,
            notification_type="REFUND_COMPLETED",
            title=f"Refund Issued ({refund_type})",
            message=f"₹{float(refund_amt):.2f} refunded for {booking.booking_reference}. Reason: {reason}.",
            severity="INFO",
        )

        return refund

    @classmethod
    def cancel_booking_with_policy(
        cls,
        booking_id: int,
        reason: str = "User requested cancellation",
    ) -> Dict[str, Any]:
        """Apply cancellation rules based on dispatch status and weather conditions."""
        booking = db.session.get(DroneBooking, booking_id)
        if not booking:
            raise PaymentServiceError(f"Booking #{booking_id} not found.")

        if booking.status in (BookingStatus.DELIVERED.value, BookingStatus.CANCELLED.value):
            raise PaymentServiceError(f"Cannot cancel booking with terminal status '{booking.status}'.")

        # If booking is unpaid, simply cancel and release drone
        latest_pay = booking.latest_payment
        if not latest_pay or latest_pay.payment_status != PaymentStatus.PAID.value:
            booking.status = BookingStatus.CANCELLED.value
            drone = db.session.get(Drone, booking.drone_id)
            if drone and drone.status == DroneStatus.RESERVED.value:
                drone.status = DroneStatus.AVAILABLE.value
            db.session.commit()
            return {"status": "CANCELLED_UNPAID", "refund_amount": 0.0, "cancellation_fee": 0.0}

        # Booking is paid: apply policy
        # If in-flight, disallow arbitrary cancellation (must divert)
        if booking.status == BookingStatus.IN_FLIGHT.value:
            raise PaymentServiceError("Cannot cancel mission currently in-flight. Emergency diversion required.")

        # Pre-dispatch cancellation:
        # Full refund if cancelled due to weather or before dispatch
        paid_amt = Decimal(str(latest_pay.final_amount))
        refund = cls.process_refund(
            booking_id=booking.id,
            amount=paid_amt,
            reason=reason,
            refund_type="FULL",
        )
        return {
            "status": "REFUNDED",
            "refund_reference": refund.refund_reference,
            "refund_amount": float(paid_amt),
            "cancellation_fee": 0.0,
        }

    @classmethod
    def generate_invoice(cls, booking_id: int) -> Dict[str, Any]:
        """Generate final itemized delivery invoice."""
        booking = db.session.get(DroneBooking, booking_id)
        if not booking:
            raise PaymentServiceError(f"Booking #{booking_id} not found.")

        quote = booking.quote
        payment = booking.latest_payment
        refunds = booking.refund_transactions.all()

        total_refunded = sum((float(r.amount) for r in refunds), 0.0)
        net_charged = float(booking.final_price) - total_refunded

        items_breakdown = {
            "base_fare": float(quote.base_fare) if quote else 100.0,
            "distance_charge": float(quote.distance_charge) if quote else 0.0,
            "weight_charge": float(quote.weight_charge) if quote else 0.0,
            "priority_charge": float(quote.priority_charge) if quote else 0.0,
            "priority_fee": float(quote.priority_charge) if quote else 0.0,
            "service_fee": float(quote.service_fee) if quote else 30.0,
            "subtotal": float(booking.final_price) - (float(quote.tax_amount) if quote else 0.0),
            "tax_rate_percent": float(quote.pricing_config.tax_rate_percent) if quote and quote.pricing_config else 5.0,
            "tax_amount": float(quote.tax_amount) if quote else 0.0,
            "total_amount": float(booking.final_price),
            "gross_total": float(booking.final_price),
        }

        pay_info = {
            "transaction_reference": payment.transaction_reference if payment else None,
            "payment_method": payment.payment_method if payment else "UNPAID",
            "payment_status": payment.payment_status if payment else "UNPAID",
            "paid_at": payment.paid_at.isoformat() if payment and payment.paid_at else None,
            "created_at": payment.created_at.isoformat() if payment and payment.created_at else None,
            "settled_at": payment.paid_at.isoformat() if payment and payment.paid_at else None,
            "idempotency_key": payment.idempotency_key if payment else None,
        }

        return {
            "invoice_number": f"INV-{booking.booking_reference}",
            "invoice_reference": f"INV-{booking.booking_reference}",
            "booking_reference": booking.booking_reference,
            "date": booking.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if booking.created_at else None,
            "created_at": booking.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if booking.created_at else None,
            "payment_status": payment.payment_status if payment else "UNPAID",
            "requester": {
                "name": booking.requester.full_name if booking.requester else "Unknown",
                "email": booking.requester.email if booking.requester else "",
                "role": booking.requester.role if booking.requester else "REQUESTER",
            },
            "drone": {
                "code": booking.drone.drone_code if booking.drone else None,
                "drone_id_code": booking.drone.drone_code if booking.drone else None,
                "model": booking.drone.model_name if booking.drone else None,
            },
            "mission": {
                "cargo_category": quote.cargo_category if quote else "Medical",
                "cargo_weight_kg": float(quote.cargo_weight_kg) if quote else 0.0,
                "priority": quote.priority if quote else "HIGH",
                "flight_distance_km": float(quote.flight_distance_km) if quote else 0.0,
                "status": booking.status,
            },
            "items": items_breakdown,
            "itemized_charges": items_breakdown,
            "payment": pay_info,
            "refunds": {
                "list": [r.to_dict() for r in refunds],
                "total_refunded": total_refunded,
            },
            "total_refunded": total_refunded,
            "net_amount_paid": max(0.0, net_charged),
        }
