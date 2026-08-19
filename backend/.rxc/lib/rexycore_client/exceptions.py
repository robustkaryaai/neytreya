"""
RexyCore Client Exceptions.
"""

class RexyClientError(Exception):
    """Base exception for all RexyCore Client errors."""
    pass

class ConnectionFailedError(RexyClientError):
    """Raised when the client fails to connect to the Hub."""
    pass

class RegistrationFailedError(RexyClientError):
    """Raised when the client fails to register with the Hub."""
    pass

class AuthenticationFailedError(RexyClientError):
    """Raised when the client fails to authenticate with the Hub."""
    pass

class TransportError(RexyClientError):
    """Raised when a lower-level transport error occurs."""
    pass

class DeviceVerificationFailedError(RexyClientError):
    """Raised when the device fails legitimacy verification."""
    pass
