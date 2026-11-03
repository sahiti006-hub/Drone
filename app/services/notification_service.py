"""In-app multi-role notification dispatch and alert management service."""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from app.extensions import db
from app.models.notification import Notification, NotificationType


class NotificationService:
    """Dispatches and tracks persistent in-app notifications across operational roles."""

    @classmethod
    def create_notification(
        cls,
        title: str,
        message: str,
        notification_type: str = NotificationType.BOOKING_CONFIRMED.value,
        user_id: Optional[int] = None,
        target_role: Optional[str] = None,
        booking_id: Optional[int] = None,
        delivery_request_id: Optional[int] = None,
        severity: str = "INFO",
    ) -> Notification:
        """Create and persist an in-app notification."""
        notif = Notification(
            user_id=user_id,
            target_role=target_role,
            booking_id=booking_id,
            delivery_request_id=delivery_request_id,
            notification_type=notification_type,
            title=title,
            message=message,
            severity=severity,
            is_read=False,
        )
        db.session.add(notif)
        db.session.commit()
        return notif

    @classmethod
    def get_notifications_for_user(
        cls,
        user_id: int,
        user_role: str,
        limit: int = 30,
        unread_only: bool = False,
    ) -> List[Notification]:
        """Fetch notifications relevant to a user or their operational role."""
        query = Notification.query.filter(
            db.or_(
                Notification.user_id == user_id,
                Notification.target_role == user_role,
                Notification.target_role == "ALL",
            )
        )
        if unread_only:
            query = query.filter_by(is_read=False)

        return query.order_by(Notification.created_at.desc()).limit(limit).all()

    @classmethod
    def get_unread_count(cls, user_id: int, user_role: str) -> int:
        """Return total unread notifications for navigation badge counter."""
        return Notification.query.filter(
            db.or_(
                Notification.user_id == user_id,
                Notification.target_role == user_role,
                Notification.target_role == "ALL",
            ),
            Notification.is_read == False,
        ).count()

    @classmethod
    def mark_as_read(cls, notification_id: int, user_id: int) -> bool:
        """Mark single notification as read."""
        notif = db.session.get(Notification, notification_id)
        if notif and (notif.user_id == user_id or notif.user_id is None):
            notif.is_read = True
            db.session.commit()
            return True
        return False

    @classmethod
    def mark_all_as_read(cls, user_id: int, user_role: str) -> int:
        """Mark all relevant notifications as read for current user session."""
        notifications = Notification.query.filter(
            db.or_(
                Notification.user_id == user_id,
                Notification.target_role == user_role,
                Notification.target_role == "ALL",
            ),
            Notification.is_read == False,
        ).all()

        count = len(notifications)
        for n in notifications:
            n.is_read = True
        db.session.commit()
        return count
