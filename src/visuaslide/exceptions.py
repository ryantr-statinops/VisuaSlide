"""Typed errors exposed by VisuaSlide."""


class VisuaSlideError(Exception):
    """Base class for expected project, data, and reporting failures."""


class ConfigurationError(VisuaSlideError):
    """Raised when project configuration is invalid."""


class DataValidationError(VisuaSlideError):
    """Raised when a source snapshot does not match its declared schema."""


class StorageError(VisuaSlideError):
    """Raised when a run artifact cannot safely be stored or loaded."""


class PublishingError(VisuaSlideError):
    """Raised when a report cannot be safely published."""


class OutputReconciliationError(PublishingError):
    """Raised when a managed output identity cannot be reconciled safely."""


class LockUnavailableError(VisuaSlideError):
    """Raised when another process is already operating on this project."""


class TransientAdapterError(VisuaSlideError):
    """Raised by an adapter when a temporary transport or service failure may recover."""
