# Exception types shared across evalapp modules.


class SpecError(Exception):
    """Pre-effect specification error: nothing was executed (exit 2)."""


class RuntimeFailure(Exception):
    """Runtime failure, fail-fast (exit 1)."""


class FailFastAbort(Exception):
    """The fail-fast block is already printed; main maps this to exit 1."""


class CommandStop(Exception):
    """Stop a command early; its message is already printed. main returns
    code (0: nothing to do, 2: configuration errors)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code
