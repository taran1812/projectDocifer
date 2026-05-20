from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class PdfFileInfo:
    path: Path
    filename: str
    content_hash: str
    file_size_bytes: int


def inspect_pdf_file(source_path: Path) -> PdfFileInfo:
    source_path = source_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"PDF not found: {source_path}")
    if not source_path.is_file():
        raise ValueError(f"Expected a PDF file, got directory: {source_path}")
    if source_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {source_path.name}")

    hasher = sha256()
    with source_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)

    return PdfFileInfo(
        path=source_path,
        filename=source_path.name,
        content_hash=hasher.hexdigest(),
        file_size_bytes=source_path.stat().st_size,
    )
