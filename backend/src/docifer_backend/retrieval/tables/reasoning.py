from __future__ import annotations

import re

from docifer_backend.retrieval.tables.schemas import (
    TableObservation,
    TableQuestionIntent,
    TableQueryResult,
    TableReasoningResult,
)


METRIC_ALIASES = [
    "net interest income",
    "noninterest revenue",
    "total net revenue",
    "net income",
    "revenue",
    "assets",
    "liabilities",
    "return on equity",
    "overhead ratio",
]
KNOWN_ENTITY_LABELS = [
    "Consumer & Community Banking",
    "Commercial & Investment Bank",
    "Asset & Wealth Management",
    "Corporate",
    "Reconciling Items",
    "Total",
    "Productivity and Business Processes",
    "Intelligent Cloud",
    "More Personal Computing",
]
NUMBER_PATTERN = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?\s*%?")


def reason_over_table_evidence(
    *,
    question: str,
    tables: list[TableQueryResult],
) -> TableReasoningResult:
    intent = parse_table_question_intent(question)
    if intent.metric is None or intent.year is None:
        return TableReasoningResult(
            status="unsupported_intent",
            intent=intent,
            observations=[],
            selected_observation=None,
            used_table_ids=[],
            used_citation_ids=[],
            reasoning_text=None,
        )

    observations: list[TableObservation] = []
    for evidence_index, table in enumerate(tables, start=1):
        citation_id = f"T{evidence_index}"
        observations.extend(
            _observations_from_structured_table(
                table,
                intent=intent,
                citation_id=citation_id,
                evidence_index=evidence_index,
            )
        )
        observations.extend(
            _observations_from_fallback_text(
                table,
                intent=intent,
                citation_id=citation_id,
                evidence_index=evidence_index,
            )
        )

    selected = _select_observation(observations, intent)
    if selected is None:
        return TableReasoningResult(
            status="no_observation",
            intent=intent,
            observations=observations,
            selected_observation=None,
            used_table_ids=[],
            used_citation_ids=[],
            reasoning_text=None,
        )

    return TableReasoningResult(
        status="supported",
        intent=intent,
        observations=observations,
        selected_observation=selected,
        used_table_ids=[selected.table_id],
        used_citation_ids=[selected.citation_id],
        reasoning_text=_format_reasoning_text(intent, observations, selected),
    )


def parse_table_question_intent(question: str) -> TableQuestionIntent:
    normalized = question.lower()
    metric = next((candidate for candidate in METRIC_ALIASES if candidate in normalized), None)
    year_match = re.search(r"\b(20\d\d)\b", normalized)
    year = int(year_match.group(1)) if year_match else None
    if any(term in normalized for term in ("highest", "largest", "maximum", "most")):
        operation = "max"
    elif any(term in normalized for term in ("lowest", "smallest", "minimum", "least")):
        operation = "min"
    elif "compare" in normalized:
        operation = "compare"
    else:
        operation = "lookup"

    entity_hint = None
    if "segment" in normalized:
        entity_hint = "segment"
    elif "country" in normalized:
        entity_hint = "country"

    matches = [value for value in [metric, str(year) if year else None, operation, entity_hint] if value]
    return TableQuestionIntent(
        metric=metric,
        year=year,
        operation=operation,
        entity_hint=entity_hint,
        matches=matches,
    )


def parse_numeric_value(value: str) -> float | None:
    token = value.strip()
    if not token or token in {"-", "—", "NA", "NM"}:
        return None
    is_negative = token.startswith("(") and token.endswith(")")
    cleaned = token.strip("()").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return -parsed if is_negative else parsed


def _observations_from_structured_table(
    table: TableQueryResult,
    *,
    intent: TableQuestionIntent,
    citation_id: str,
    evidence_index: int,
) -> list[TableObservation]:
    if not table.structured_json:
        return []
    metric = intent.metric or ""
    headers = [str(header).strip() for header in table.structured_json.get("headers") or []]
    rows = [[str(cell).strip() for cell in row] for row in table.structured_json.get("rows") or []]
    if not headers or not rows:
        return []

    context = " ".join(
        item
        for item in [
            table.title,
            table.caption,
            table.section_heading,
            table.raw_text,
            " ".join(headers),
        ]
        if item
    ).lower()
    year_index = _find_year_index(headers, intent.year)
    if year_index is None:
        return []

    observations: list[TableObservation] = []
    context_has_metric = metric in context
    for row in rows:
        if len(row) <= year_index:
            continue
        label = row[0].strip()
        row_text = " | ".join(row)
        row_has_metric = metric in row_text.lower()
        if not context_has_metric and not row_has_metric:
            continue
        value = parse_numeric_value(row[year_index])
        if value is None:
            continue
        observations.append(
            TableObservation(
                label=label,
                metric=metric,
                year=intent.year,
                value=value,
                display_value=_display_value(value, row[year_index], table.raw_text),
                unit=_infer_unit(row_text, table.raw_text),
                table_id=table.table_id,
                citation_id=citation_id,
                evidence_index=evidence_index,
                row_text=row_text,
            )
        )
    return observations


def _observations_from_fallback_text(
    table: TableQueryResult,
    *,
    intent: TableQuestionIntent,
    citation_id: str,
    evidence_index: int,
) -> list[TableObservation]:
    if not table.raw_text or not intent.metric:
        return []
    lines = [line.strip() for line in table.raw_text.splitlines() if line.strip()]
    if not lines:
        return []

    observations: list[TableObservation] = []
    observations.extend(
        _fallback_segment_matrix_observations(
            table,
            lines=lines,
            intent=intent,
            citation_id=citation_id,
            evidence_index=evidence_index,
        )
    )
    observations.extend(
        _fallback_simple_row_observations(
            table,
            lines=lines,
            intent=intent,
            citation_id=citation_id,
            evidence_index=evidence_index,
        )
    )
    return _dedupe_observations(observations)


def _fallback_segment_matrix_observations(
    table: TableQueryResult,
    *,
    lines: list[str],
    intent: TableQuestionIntent,
    citation_id: str,
    evidence_index: int,
) -> list[TableObservation]:
    observations: list[TableObservation] = []
    for entity_line_index, line in enumerate(lines):
        labels = _labels_in_line(line)
        if len(labels) < 2:
            continue
        year_line_index = _find_following_year_line(lines, entity_line_index + 1)
        if year_line_index is None:
            continue
        years = [int(year) for year in re.findall(r"\b20\d\d\b", lines[year_line_index])]
        if not years or len(years) < len(labels):
            continue
        metric_line = _find_metric_line(lines, year_line_index + 1, intent.metric or "")
        if metric_line is None:
            continue
        values = _numbers_from_line(metric_line)
        if len(values) < len(years):
            continue

        group_width = max(1, len(years) // len(labels))
        unit = _infer_unit(metric_line, table.raw_text)
        for label_index, label in enumerate(labels):
            group_start = label_index * group_width
            group_years = years[group_start:group_start + group_width]
            try:
                offset = group_years.index(intent.year)
            except ValueError:
                continue
            value_index = group_start + offset
            if value_index >= len(values):
                continue
            token, value = values[value_index]
            observations.append(
                TableObservation(
                    label=label,
                    metric=intent.metric or "",
                    year=intent.year,
                    value=value,
                    display_value=_display_value(value, token, table.raw_text),
                    unit=unit,
                    table_id=table.table_id,
                    citation_id=citation_id,
                    evidence_index=evidence_index,
                    row_text=metric_line,
                )
            )
    return observations


def _fallback_simple_row_observations(
    table: TableQueryResult,
    *,
    lines: list[str],
    intent: TableQuestionIntent,
    citation_id: str,
    evidence_index: int,
) -> list[TableObservation]:
    observations: list[TableObservation] = []
    for index, line in enumerate(lines):
        if not intent.metric or intent.metric not in line.lower():
            continue
        header = _find_previous_year_header(lines, index)
        if not header:
            continue
        headers = re.findall(r"\b20\d\d\b", header)
        values = _numbers_from_line(line)
        if not headers or not values:
            continue
        for year_index, year in enumerate(headers):
            if int(year) != intent.year or year_index >= len(values):
                continue
            token, value = values[year_index]
            observations.append(
                TableObservation(
                    label=_row_label(line, intent.metric),
                    metric=intent.metric,
                    year=intent.year,
                    value=value,
                    display_value=_display_value(value, token, table.raw_text),
                    unit=_infer_unit(line, table.raw_text),
                    table_id=table.table_id,
                    citation_id=citation_id,
                    evidence_index=evidence_index,
                    row_text=line,
                )
            )
    return observations


def _select_observation(
    observations: list[TableObservation],
    intent: TableQuestionIntent,
) -> TableObservation | None:
    if not observations:
        return None
    if intent.entity_hint == "segment":
        segment_observations = [
            item for item in observations
            if item.label in KNOWN_ENTITY_LABELS and item.label not in {"Total", "Reconciling Items"}
        ]
        if segment_observations:
            observations = segment_observations
    if intent.operation == "max":
        return sorted(observations, key=lambda item: (-item.value, item.evidence_index, item.label))[0]
    if intent.operation == "min":
        return sorted(observations, key=lambda item: (item.value, item.evidence_index, item.label))[0]
    return sorted(observations, key=lambda item: (item.evidence_index, item.label))[0]


def _format_reasoning_text(
    intent: TableQuestionIntent,
    observations: list[TableObservation],
    selected: TableObservation,
) -> str:
    comparable = [
        item for item in observations
        if item.metric == selected.metric and item.year == selected.year and item.citation_id == selected.citation_id
    ]
    candidates = "; ".join(
        f"{item.label}: {item.display_value}"
        for item in comparable[:8]
    )
    operation = {
        "max": "highest",
        "min": "lowest",
    }.get(intent.operation, "selected")
    return (
        "Computed table observation:\n"
        f"Metric: {selected.metric}\n"
        f"Year: {selected.year or 'unknown'}\n"
        f"Operation: {intent.operation}\n"
        f"Candidates from {selected.citation_id}: {candidates}\n"
        f"Result: {selected.label} has the {operation} value at {selected.display_value}. "
        f"Cite {selected.citation_id} for this result."
    )


def _find_year_index(headers: list[str], year: int | None) -> int | None:
    if year is None:
        return None
    for index, header in enumerate(headers):
        if str(year) in header:
            return index
    return None


def _labels_in_line(line: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    lower = line.lower()
    for label in KNOWN_ENTITY_LABELS:
        position = lower.find(label.lower())
        if position >= 0:
            matches.append((position, label))
    matches.sort(key=lambda item: item[0])
    return [label for _, label in matches]


def _find_following_year_line(lines: list[str], start_index: int) -> int | None:
    for index in range(start_index, min(len(lines), start_index + 5)):
        if len(re.findall(r"\b20\d\d\b", lines[index])) >= 2:
            return index
    return None


def _find_metric_line(lines: list[str], start_index: int, metric: str) -> str | None:
    for index in range(start_index, min(len(lines), start_index + 10)):
        if metric in lines[index].lower():
            return lines[index]
    return None


def _find_previous_year_header(lines: list[str], line_index: int) -> str | None:
    for index in range(line_index - 1, max(-1, line_index - 6), -1):
        if re.search(r"\b20\d\d\b", lines[index]):
            return lines[index]
    return None


def _numbers_from_line(line: str) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for match in NUMBER_PATTERN.findall(line):
        parsed = parse_numeric_value(match)
        if parsed is not None:
            values.append((match.strip(), parsed))
    return values


def _display_value(value: float, source_token: str, context: str) -> str:
    unit = _infer_unit(source_token, context)
    number = f"{int(value):,}" if value.is_integer() else f"{value:,.2f}"
    if source_token.strip().endswith("%"):
        return f"{number}%"
    prefix = "$" if "$" in context or "$" in source_token else ""
    suffix = f" {unit}" if unit and unit != "percent" else ""
    return f"{prefix}{number}{suffix}"


def _infer_unit(row_text: str, context: str) -> str | None:
    combined = f"{row_text}\n{context}".lower()
    if "%" in row_text:
        return "percent"
    if "in millions" in combined or "in millions," in combined:
        return "million"
    if "in billions" in combined or "in billions," in combined:
        return "billion"
    if "trillion" in combined:
        return "trillion"
    if "billion" in combined:
        return "billion"
    if "million" in combined:
        return "million"
    return None


def _row_label(line: str, metric: str) -> str:
    label = re.split(NUMBER_PATTERN, line, maxsplit=1)[0].strip(" :-|")
    return label or metric


def _dedupe_observations(observations: list[TableObservation]) -> list[TableObservation]:
    seen: set[tuple[str, str, int | None, float, str]] = set()
    deduped: list[TableObservation] = []
    for item in observations:
        key = (item.label, item.metric, item.year, item.value, item.table_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
