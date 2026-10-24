from .errors import SpecError


def resolve_selection(occurrences, datasets):
    """Resolve --select occurrences to {dataset name: sorted entry indices}.

    ``occurrences`` is the parsed --select value (list of token lists);
    ``datasets`` is the ordered name -> Dataset map. No flag (None/empty)
    means full scope: every configured dataset, every entry.
    """
    names = list(datasets)
    if not occurrences:
        return {name: list(range(len(datasets[name].entries))) for name in names}

    selected = {name: set() for name in names}
    for tokens in occurrences:
        if not tokens:
            raise SpecError("--select occurrence has no dataset name")
        dataset_token, specs = tokens[0], tokens[1:]
        if dataset_token == "*":
            if len(tokens) != 1:
                raise SpecError(
                    "unknown dataset '*' (a bare --select * is the only "
                    "form that selects all datasets)"
                )
            for name in names:
                selected[name].update(range(len(datasets[name].entries)))
            continue
        if dataset_token not in datasets:
            raise SpecError(
                f"unknown dataset '{dataset_token}' (configured: {', '.join(names)})"
            )
        dataset = datasets[dataset_token]
        if not specs:
            raise SpecError(
                f"--select '{dataset_token}' has no entry specs; use "
                "'*' for all entries or give #position / @id specs"
            )
        for spec in specs:
            selected[dataset_token].update(_resolve_spec(dataset, spec))
    return {name: sorted(selected[name]) for name in names}


def _resolve_spec(dataset, spec):
    if spec == "*":
        return list(range(len(dataset.entries)))
    if spec.startswith("#"):
        return _resolve_positions(dataset, spec[1:])
    if spec.startswith("@"):
        return _resolve_id(dataset, spec[1:])
    raise SpecError(
        f"malformed entry spec '{spec}' in dataset '{dataset.name}' "
        "(expected '#position', '@id', or '*')"
    )


def _resolve_positions(dataset, body):
    if not body:
        raise SpecError(f"malformed entry spec '#' in dataset '{dataset.name}'")
    indices = set()
    for element in body.split(","):
        if not element:
            raise SpecError(
                f"malformed entry spec '#{body}' in dataset '{dataset.name}'"
            )
        if "-" in element:
            parts = element.split("-")
            if len(parts) != 2:
                raise SpecError(
                    f"malformed range '{element}' in dataset '{dataset.name}'"
                )
            start_text, end_text = parts
            if not (start_text.isascii() and start_text.isdigit()) or not (
                end_text.isascii() and end_text.isdigit()
            ):
                raise SpecError(
                    f"malformed range '{element}' in dataset '{dataset.name}'"
                )
            start, end = int(start_text), int(end_text)
            if start > end:
                raise SpecError(
                    f"invalid range '{element}' in dataset '{dataset.name}': "
                    "start exceeds end"
                )
            if end >= len(dataset.entries):
                raise SpecError(
                    f"entry index {end} out of range in dataset '{dataset.name}' "
                    f"(0-{len(dataset.entries) - 1})"
                )
            indices.update(range(start, end + 1))
        else:
            if not (element.isascii() and element.isdigit()):
                raise SpecError(
                    f"malformed entry position '{element}' in dataset "
                    f"'{dataset.name}'"
                )
            index = int(element)
            if index >= len(dataset.entries):
                raise SpecError(
                    f"entry index {index} out of range in dataset "
                    f"'{dataset.name}' (0-{len(dataset.entries) - 1})"
                )
            indices.add(index)
    return indices


def _resolve_id(dataset, entry_id):
    if not dataset.id_map:
        raise SpecError(
            f"@id specs are not valid in unnamed dataset '{dataset.name}' "
            "(it declares no entry_id_field)"
        )
    if entry_id not in dataset.id_map:
        raise SpecError(
            f"no entry with id '{entry_id}' in dataset '{dataset.name}'"
        )
    return {dataset.id_map[entry_id]}
