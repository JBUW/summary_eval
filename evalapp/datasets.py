import csv
import json
from dataclasses import dataclass, field

from .errors import SpecError


@dataclass
class Dataset:
    name: str
    decl: dict
    entries: list
    id_map: dict = field(default_factory=dict)


def load_dataset(name, decl):
    """Load one configured dataset (contract R1: fail fast, exit 2)."""
    path = decl["path"]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise SpecError(f"dataset '{name}': file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or exc
        raise SpecError(f"dataset '{name}': cannot read {path}: {detail}") from None

    extension = path.rsplit(".", 1)[1].lower() if "." in path else ""
    if extension == "csv":
        entries, id_map = _load_csv(name, path, text, decl)
    elif extension in ("jsonl", "json"):
        entries, id_map = _load_json_lines(name, path, text, decl)
    else:
        raise SpecError(
            f"dataset '{name}': unsupported file extension '{extension}' "
            "(supported: .csv, .jsonl, .json)"
        )

    if not entries:
        raise SpecError(f"dataset '{name}': no entries in {path}")
    return Dataset(name=name, decl=decl, entries=entries, id_map=id_map)


def _load_csv(name, path, text, decl):
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return [], {}
    header = rows[0]
    for required in ("transcript_field", "reference_field", "entry_id_field"):
        column = decl.get(required)
        if column is not None and column not in header:
            raise SpecError(
                f"dataset '{name}': field '{column}' not found in {path} "
                f"(columns: {', '.join(header)})"
            )
    entries = []
    id_map = {}
    for row, number in zip(rows[1:], range(2, len(rows) + 1)):
        if len(row) != len(header):
            raise SpecError(
                f"dataset '{name}': malformed line {number} in {path}: "
                f"expected {len(header)} columns, got {len(row)}"
            )
        if not any(cell.strip() for cell in row):
            raise SpecError(
                f"dataset '{name}': malformed line {number} in {path}: empty row"
            )
        record = dict(zip(header, row))
        entries.append(
            {"index": len(entries), "transcript": record[decl["transcript_field"]]}
        )
        if decl.get("entry_id_field") is not None:
            entry_id = record[decl["entry_id_field"]]
            entries[-1]["entry_id"] = entry_id
            id_map[entry_id] = len(entries) - 1
    return entries, id_map


def _load_json_lines(name, path, text, decl):
    entries = []
    id_map = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise SpecError(
                f"dataset '{name}': malformed line {number} in {path}: empty line"
            )
        try:
            object_ = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SpecError(
                f"dataset '{name}': malformed line {number} in {path}: "
                f"not a JSON object: {exc}"
            ) from None
        if not isinstance(object_, dict):
            raise SpecError(
                f"dataset '{name}': malformed line {number} in {path}: "
                "expected a JSON object"
            )
        for required in ("transcript_field", "reference_field", "entry_id_field"):
            key = decl.get(required)
            if key is not None and key not in object_:
                raise SpecError(
                    f"dataset '{name}': field '{key}' not found in {path} "
                    f"(line {number})"
                )
        entries.append(
            {"index": len(entries), "transcript": object_[decl["transcript_field"]]}
        )
        if decl.get("entry_id_field") is not None:
            entry_id = object_[decl["entry_id_field"]]
            entries[-1]["entry_id"] = entry_id
            id_map[entry_id] = len(entries) - 1
    return entries, id_map
