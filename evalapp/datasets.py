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
    if extension not in ("csv", "jsonl", "json"):
        raise SpecError(
            f"dataset '{name}': unsupported file extension '{extension}' "
            "(supported: .csv, .jsonl, .json)"
        )

    entries, id_map, errors = _load(name, path, text, decl)
    if errors:
        raise SpecError(errors[0])
    return Dataset(name=name, decl=decl, entries=entries, id_map=id_map)


def _is_empty(value):
    return value is None or value == ""


def _load(name, path, text, decl):
    """Collect mode: (entries, id_map, errors) in contract error order."""
    extension = path.rsplit(".", 1)[1].lower() if "." in path else ""
    if extension == "csv":
        entries, id_map, errors = _load_csv(name, path, text, decl)
    else:
        entries, id_map, errors = _load_json_lines(name, path, text, decl)
    if not entries:
        errors.append(f"dataset '{name}': no entries in {path}")
    return entries, id_map, errors


def _value_checks(name, path, decl, parsed):
    errors = []
    transcript_key = decl["transcript_field"]
    reference_key = decl.get("reference_field")
    id_key = decl.get("entry_id_field")
    seen_ids = set()
    for number, record in parsed:
        if transcript_key in record and _is_empty(record[transcript_key]):
            errors.append(
                f"dataset '{name}': empty transcript in {path} (line {number})"
            )
        if id_key is not None and id_key in record:
            entry_id = record[id_key]
            if _is_empty(entry_id):
                errors.append(
                    f"dataset '{name}': empty entry id in {path} (line {number})"
                )
            elif entry_id in seen_ids:
                errors.append(
                    f"dataset '{name}': duplicate entry id '{entry_id}' in {path} "
                    f"(line {number})"
                )
            else:
                seen_ids.add(entry_id)
        if (
            reference_key is not None
            and reference_key in record
            and _is_empty(record[reference_key])
        ):
            errors.append(f"dataset '{name}': empty reference in {path} (line {number})")
    return errors


def _load_csv(name, path, text, decl):
    errors = []
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return [], {}, errors
    header = rows[0]
    seen = set()
    reported = set()
    for column in header:
        if column in seen and column not in reported:
            errors.append(
                f"dataset '{name}': duplicate column name '{column}' in {path}"
            )
            reported.add(column)
        seen.add(column)
    for required in ("transcript_field", "reference_field", "entry_id_field"):
        column = decl.get(required)
        if column is not None and column not in header:
            errors.append(
                f"dataset '{name}': field '{column}' not found in {path} "
                f"(columns: {', '.join(header)})"
            )
    transcript_key = decl["transcript_field"]
    id_key = decl.get("entry_id_field")
    entries = []
    id_map = {}
    parsed = []
    for row, number in zip(rows[1:], range(2, len(rows) + 1)):
        if len(row) != len(header):
            errors.append(
                f"dataset '{name}': malformed line {number} in {path}: "
                f"expected {len(header)} columns, got {len(row)}"
            )
            continue
        if not any(cell.strip() for cell in row):
            errors.append(
                f"dataset '{name}': malformed line {number} in {path}: empty row"
            )
            continue
        record = dict(zip(header, row))
        entry = {"index": len(entries)}
        if transcript_key in record:
            entry["transcript"] = record[transcript_key]
        entries.append(entry)
        if id_key is not None and id_key in record:
            entry_id = record[id_key]
            entry["entry_id"] = entry_id
            id_map[entry_id] = len(entries) - 1
        parsed.append((number, record))
    errors.extend(_value_checks(name, path, decl, parsed))
    return entries, id_map, errors


def _load_json_lines(name, path, text, decl):
    errors = []
    transcript_key = decl["transcript_field"]
    id_key = decl.get("entry_id_field")
    entries = []
    id_map = {}
    parsed = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            errors.append(
                f"dataset '{name}': malformed line {number} in {path}: empty line"
            )
            continue
        try:
            object_ = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                f"dataset '{name}': malformed line {number} in {path}: "
                f"not a JSON object: {exc}"
            )
            continue
        if not isinstance(object_, dict):
            errors.append(
                f"dataset '{name}': malformed line {number} in {path}: "
                "expected a JSON object"
            )
            continue
        for required in ("transcript_field", "reference_field", "entry_id_field"):
            key = decl.get(required)
            if key is not None and key not in object_:
                errors.append(
                    f"dataset '{name}': field '{key}' not found in {path} "
                    f"(line {number})"
                )
        entry = {"index": len(entries)}
        if transcript_key in object_:
            entry["transcript"] = object_[transcript_key]
        entries.append(entry)
        if id_key is not None and id_key in object_:
            entry_id = object_[id_key]
            entry["entry_id"] = entry_id
            id_map[entry_id] = len(entries) - 1
        parsed.append((number, object_))
    errors.extend(_value_checks(name, path, decl, parsed))
    return entries, id_map, errors
