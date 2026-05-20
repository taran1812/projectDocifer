from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from docifer_backend.config.settings import get_settings


@dataclass
class TraceRecorder:
    enabled: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    _run: Any = None

    def add_outputs(self, outputs: dict[str, Any]) -> None:
        self.outputs.update(outputs)
        if self._run is not None:
            self._run.add_outputs(outputs)


@contextmanager
def evaluation_trace(
    *,
    name: str,
    inputs: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    enabled: bool | None = None,
) -> Iterator[TraceRecorder]:
    settings = get_settings()
    trace_enabled = (
        settings.langsmith_tracing
        and bool(settings.langsmith_api_key)
        if enabled is None
        else enabled
    )
    if not trace_enabled:
        yield TraceRecorder(enabled=False)
        return

    from langsmith import Client
    from langsmith.run_helpers import trace, tracing_context

    client = Client(api_key=settings.langsmith_api_key)
    trace_tags = ["docifer", "phase5", "evaluation"] + (tags or [])
    trace_metadata = metadata or {}

    with tracing_context(
        project_name=settings.langsmith_project,
        enabled=True,
        client=client,
        tags=trace_tags,
        metadata=trace_metadata,
    ):
        with trace(
            name,
            run_type="chain",
            inputs=inputs,
            project_name=settings.langsmith_project,
            client=client,
            tags=trace_tags,
            metadata=trace_metadata,
        ) as run:
            recorder = TraceRecorder(enabled=True, _run=run)
            yield recorder
