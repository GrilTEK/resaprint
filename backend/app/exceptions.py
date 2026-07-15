class NotAuthenticatedHtml(Exception):
    """Raised by HTML-route auth deps; handled by redirecting to /login."""


class ForbiddenHtml(Exception):
    """Raised when an authenticated but insufficiently-privileged user
    (e.g. a reception-role PIN) hits an admin-only HTML page; handled
    by redirecting to the dashboard."""
