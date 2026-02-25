"""Custom exceptions for CircuitAI."""


class CircuitAIError(Exception):
    """Base exception for all CircuitAI errors."""


class DatabaseError(CircuitAIError):
    """Database connection or query error."""


class EncryptionError(CircuitAIError):
    """Encryption/decryption error."""


class ConfigError(CircuitAIError):
    """Configuration error."""


class ValidationError(CircuitAIError):
    """Data validation error."""


class NotFoundError(CircuitAIError):
    """Entity not found."""


class DuplicateError(CircuitAIError):
    """Duplicate entity."""


class AdapterError(CircuitAIError):
    """Adapter/plugin error."""


class CalendarSyncError(CircuitAIError):
    """Calendar sync error."""


class ParseError(CircuitAIError):
    """Text parsing error."""
