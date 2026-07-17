class SupervisorHalt(Exception):
    """Raised to unwind a run when the supervisor decides it must stop."""


class WallClockExceeded(SupervisorHalt):
    pass


class IdenticalFailureBreakerTripped(Exception):
    """Raised by callers that hit the same error signature N times on the same unit."""

    def __init__(self, signature: str, count: int):
        self.signature = signature
        self.count = count
        super().__init__(f"identical failure signature {signature!r} repeated {count}x")
