class SKStoreError(Exception):
    """Base error safe to present to a Discord user."""


class ValidationError(SKStoreError):
    pass


class PermissionDenied(SKStoreError):
    pass


class InvalidTransition(SKStoreError):
    pass


class DuplicateOperation(SKStoreError):
    pass


class MissingConfiguration(SKStoreError):
    pass


class ResourceUnavailable(SKStoreError):
    pass
