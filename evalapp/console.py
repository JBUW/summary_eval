# Console contract: four stdout prefixes with a fixed intra-run order
# (warn -> plan -> note). error: and done: are unconstrained.


class Console:
    _STAGE_WARN = 0
    _STAGE_PLAN = 1
    _STAGE_NOTE = 2

    def __init__(self):
        self._stage = -1

    def _emit(self, line, stage):
        if stage is not None:
            assert stage >= self._stage, "console message order violation"
            self._stage = stage
        print(line)

    def error(self, message):
        self._emit(f"error: {message}", None)

    def warn(self, message):
        self._emit(f"warn: {message}", self._STAGE_WARN)

    def plan(self, command, message):
        self._emit(f"plan({command}): {message}", self._STAGE_PLAN)

    def done(self, command, message):
        self._emit(f"done({command}): {message}", None)

    def note(self, message):
        self._emit(f"note: {message}", self._STAGE_NOTE)

    def log(self, line):
        self._emit(line, None)
