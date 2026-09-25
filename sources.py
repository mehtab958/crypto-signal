"""Text extraction from the FPSC syllabus PDF and from the user's own book/notes PDFs."""

import re

import pymupdf

SYLLABUS_CHARS = 15000     # default: one subject's outline + suggested readings
BOOKS_CHARS = 120000       # cap on text sent from the user's own PDFs per request


def pdf_pages(data: bytes) -> list[str]:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [page.get_text() for page in doc]


def syllabus_section(syllabus_pdf: bytes, subject: str, chars: int = SYLLABUS_CHARS) -> str:
    """Best-effort slice of the syllabus covering `subject`. Prefers the heading form
    'SUBJECT (100 MARKS)', then an all-caps occurrence, then the first mention."""
    text = "\n".join(pdf_pages(syllabus_pdf))
    # "Precis & Composition" must also match "PRECIS AND COMPOSITION"
    words = [w for w in re.findall(r"\w+", subject) if len(w) > 2 and w.lower() != "and"]
    pattern = r"\W+(?:(?:and|&)\W+)?".join(map(re.escape, words))
    best = None
    for m in re.finditer(pattern, text, re.IGNORECASE):
        if re.match(r"[\s(\-:]*(\d+\s*)?marks", text[m.end(): m.end() + 40], re.IGNORECASE):
            score = 0
        elif m.group().isupper():
            score = 1
        else:
            score = 2
        if best is None or score < best[0]:
            best = (score, m.start())
        if score == 0:
            break
    return text[best[1]: best[1] + chars] if best else ""


def book_text(name: str, data: bytes) -> str:
    pages = pdf_pages(data)
    return "\n".join(f"[{name}, p. {i}]\n{t}" for i, t in enumerate(pages, 1))
