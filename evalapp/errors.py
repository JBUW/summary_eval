# Exception types shared across evalapp modules.


class SpecError(Exception):
    """Pre-effect specification error: nothing was executed (exit 2)."""


class RuntimeFailure(Exception):
    """Runtime failure, fail-fast (exit 1)."""


class FailFastAbort(Exception):
    """The fail-fast block is already printed; main maps this to exit 1."""
