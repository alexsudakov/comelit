class SafetyPocError(Exception):
    pass


class OperationExists(SafetyPocError):
    pass


class RateLimited(SafetyPocError):
    pass


class DefinitelyNotSent(SafetyPocError):
    """Transport can prove no bytes/action left the local boundary."""


class AmbiguousSend(SafetyPocError):
    """A send was attempted but outcome cannot be proven."""


class RealTransportDisabled(DefinitelyNotSent):
    """Real transport is absent, so this backend proves no send can occur."""


class SimulatedProcessCrash(BaseException):
    """Fault-injection primitive deliberately not caught by executor."""
