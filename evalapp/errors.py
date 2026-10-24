# Exception types shared across evalapp modules.


class SpecError(Exception):
    """Pre-effect specification error: nothing was executed (exit 2)."""


class RuntimeFailure(Exception):
    """Runtime failure, fail-fast (exit 1)."""
