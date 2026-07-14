class NotAuthenticatedHtml(Exception):
    """Raised by HTML-route auth deps; handled by redirecting to /login."""
