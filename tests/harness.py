"""In-process test harness for the evalapp executable.

Tests assert only external behavior: captured stdout lines and exit codes.
The harness is deliberately reusable by later tickets.
"""
import contextlib
import csv
import io
import json
import os
import sys
from dataclasses import dataclass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from evalapp.cli import main  # noqa: E402
from evalapp.metrics import registered_names  # noqa: E402


@dataclass
class RunResult:
    exit_code: int
    stdout: str

    @property
    def lines(self):
        return [line for line in self.stdout.splitlines() if line]

    def with_prefix(self, prefix):
        return [line for line in self.lines if line.startswith(prefix)]

    def assert_exit(self, code):
        assert self.exit_code == code, (
            f"exit code {self.exit_code} != {code}; stdout:\n{self.stdout}"
        )
        return self


def run_cli(argv, cwd=None):
    previous = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            try:
                code = main(list(argv))
                if code is None:
                    code = 0
            except SystemExit as exc:
                code = int(exc.code if exc.code is not None else 0)
    finally:
        if cwd is not None:
            os.chdir(previous)
    return RunResult(code, buffer.getvalue())


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def write_csv(path, header, rows):
    handle = open(path, "w", encoding="utf-8", newline="")
    try:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    finally:
        handle.close()
    return path


def write_jsonl(path, objects):
    write_text(path, "".join(json.dumps(obj) + "\n" for obj in objects))
    return path


def write_config(path, datasets, store=None, extra_top_level=None):
    config = {"datasets": datasets}
    if store is not None:
        config["store"] = store
    if extra_top_level:
        config.update(extra_top_level)
    write_text(path, json.dumps(config, indent=2) + "\n")
    return path


def standard_workspace(tmp_path, config_name="config.json"):
    """Two 12-entry JSONL datasets: 'named' (ids id-00..id-11) and 'unnamed'."""
    named = [
        {"text": f"transcript {index}", "id": f"id-{index:02d}"}
        for index in range(12)
    ]
    unnamed = [{"text": f"transcript {index}"} for index in range(12)]
    write_jsonl(str(tmp_path / "named.jsonl"), named)
    write_jsonl(str(tmp_path / "unnamed.jsonl"), unnamed)
    write_config(
        str(tmp_path / config_name),
        {
            "named": {
                "path": "named.jsonl",
                "transcript_field": "text",
                "entry_id_field": "id",
            },
            "unnamed": {"path": "unnamed.jsonl", "transcript_field": "text"},
        },
        store="store.db",
    )
    return tmp_path


def plan_count(result, command, dataset):
    for line in result.lines:
        if line.startswith(f"plan({command}): {dataset} ") and line.endswith(
            " entries"
        ):
            return int(line.split()[2])
    return None


ALL_METRICS = list(registered_names())


def add_server_section(path, port=8081):
    """Give the config a minimal valid server section (check's static stage)."""
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["server"] = {
        "command": "/bin/true",
        "args": {},
        "env": {},
        "port": port,
        "startup_timeout_s": 120,
    }
    write_text(path, json.dumps(config, indent=2) + "\n")
    return path


def discovery_lines(metric_named, metric_other, judge_named, judge_other):
    """The byte-exact six-line scorer-discovery block."""
    def value(label, names):
        return f"  {label}:".ljust(33) + (", ".join(names) if names else "(none)")
    return [
        f"metrics (registered: {len(metric_named) + len(metric_other)}):",
        value("default_metrics", metric_named),
        value("registered, not named there", metric_other),
        f"judges (configured: {len(judge_named) + len(judge_other)}):",
        value("default_judges", judge_named),
        value("configured, not named there", judge_other),
    ]


STANDARD_DISCOVERY = discovery_lines(ALL_METRICS, [], [], [])

REPO_DISCOVERY = discovery_lines(
    ["faithfulness", "key_claim_completeness",
     "conciseness_length_proxy", "structural_instruction_check"],
    ["internal_consistency"],
    ["openrouter-llama-3-70b"],
    [],
)
