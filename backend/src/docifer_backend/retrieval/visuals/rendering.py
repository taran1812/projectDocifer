from __future__ import annotations

from pathlib import Path


def render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    *,
    scale: float = 1.5,
) -> list[tuple[int, Path]]:
    """Render each PDF page to a JPEG. Returns list of (page_number_1indexed, jpeg_path)."""
    import pypdfium2 as pdfium

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[tuple[int, Path]] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                page_number = page_index + 1
                output_path = output_dir / f"page_{page_number:04d}.jpg"
                pil_image.save(str(output_path), format="JPEG", quality=85)
                rendered.append((page_number, output_path))
            finally:
                page.close()
    finally:
        pdf.close()
    return rendered
