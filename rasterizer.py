"""PDF and image rasterization utilities."""

from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


def get_page_count(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    count = doc.page_count
    doc.close()
    return count


def rasterize_page(pdf_path: str, page_num: int, dpi: int = 300) -> Image.Image:
    """Rasterize a single PDF page (1-based) to a PIL Image."""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    doc.close()
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def load_pages(file_path: str, pages: list[int] | None = None,dpi: int = 300,) -> dict[int, Image.Image]:
    """Return {page_number: PIL Image} for a PDF or image file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()

    if ext == ".pdf":
        total = get_page_count(file_path)
        page_nums = pages or list(range(1, total + 1))
        result = {}
        for p in page_nums:
            print(f"  Rasterizing page {p}/{total}...", end=" ", flush=True)
            result[p] = rasterize_page(file_path, p, dpi=dpi)
            print("done")
        return result

    elif ext in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}:
        print("  Loading image...", end=" ", flush=True)
        img = Image.open(file_path).convert("RGB")
        print("done")
        return {1: img}

    else:
        raise ValueError(f"Unsupported file type: {ext}")