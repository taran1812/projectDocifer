import argparse
import json
import sys
from pathlib import Path

from docifer_backend.ingestion.service import IngestionService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest one local PDF into Docifer.")
    parser.add_argument("source_path", type=Path)
    parser.add_argument("--force", action="store_true", help="Force a fresh parse.")
    args = parser.parse_args(argv)

    outcome = IngestionService().ingest_pdf(args.source_path, force_reprocess=args.force)
    print(json.dumps(outcome.__dict__, indent=2, sort_keys=True))
    return 0 if outcome.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
