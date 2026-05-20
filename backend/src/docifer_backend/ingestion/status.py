from enum import StrEnum


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    PARSED = "parsed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


TERMINAL_INGESTION_STATUSES = {
    IngestionStatus.PARSED,
    IngestionStatus.INDEXED,
    IngestionStatus.FAILED,
}
