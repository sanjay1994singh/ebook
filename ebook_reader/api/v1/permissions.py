import logging

from rest_framework import permissions

from ebook_reader.models import EbookDocument
from ebook_reader.services.feature_flags import (
    can_user_access_new_ebook,
    is_mobile_reader_available,
)

logger = logging.getLogger(__name__)


class CanAccessReadyEbook(permissions.BasePermission):
    """Allow access only to ready ebooks backed by published books."""

    def has_object_permission(self, request, view, obj):
        allowed = is_mobile_reader_available(obj, request.user) and can_user_access_new_ebook(
            obj,
            request.user,
        )
        if not allowed:
            logger.info(
                "ebook.api.permission_denied",
                extra={
                    "ebook_document_id": getattr(obj, "id", None),
                    "view": view.__class__.__name__,
                    "user_is_authenticated": bool(request.user and request.user.is_authenticated),
                    "user_is_staff": bool(request.user and request.user.is_staff),
                },
            )
        return allowed


class StaffDiagnosticsPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)
