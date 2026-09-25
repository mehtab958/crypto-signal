"""Text extraction from the FPSC syllabus PDF and from the user's own book/notes PDFs."""

import re
from dataclasses import dataclass, field

import pymupdf

SYLLABUS_CHARS = 15000     # default cap for one subject's outline + suggested readings
BOOKS_CHARS = 120000       # cap on text sent from the user's own PDFs per request
MIN_TEXT = 400             # less text than this means the pages are scanned images
IMAGE_DPI = 110
PAGE_HEADER = "Revised Scheme and Syllabus for CSS Competitive Examination"

# Every subject in the FPSC PDF opens with "PAPER:" and its name, e.g. "PAPER:\n  PAKISTAN AFFAIRS\n (100 MARKS)".
HEADING = re.compile(r"PAPER:\s+([A-Z][^\n]*)")


@dataclass
class SyllabusExtract:
    text: str = ""
    images: list[bytes] = field(default_factory=list)   # PNG pages, for scanned sections


def pdf_pages(data: bytes) -> list[str]:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [page.get_text() for page in doc]


def _pattern(subject: str) -> str:
    words = [w for w in re.findall(r"\w+", subject) if len(w) > 2 and w.lower() != "and"]
    return r"\W+(?:(?:and|&)\W+)?".join(map(re.escape, words))


def _find_start(text: str, subject: str) -> int | None:
    """Prefers the heading form 'SUBJECT (100 MARKS)', then an all-caps mention, then the first one.
    'Precis & Composition' also matches 'PRECIS AND COMPOSITION'."""
    pattern = _pattern(subject)
    best = None
    for m in re.finditer(pattern, text, re.IGNORECASE):
        if re.match(r"[\s(\-:)]*(\d+\s*)?marks", text[m.end(): m.end() + 40], re.IGNORECASE):
            return m.start()
        score = 1 if m.group().isupper() else 2
        if best is None or score < best[0]:
            best = (score, m.start())
    return best[1] if best else None


def syllabus_section(syllabus_pdf: bytes, subject: str, chars: int = SYLLABUS_CHARS) -> SyllabusExtract:
    """The subject's part of the syllabus, from its heading up to the next subject's heading."""
    pages = pdf_pages(syllabus_pdf)
    text = "\n".join(pages)
    start = _find_start(text, subject)
    if start is None:
        return SyllabusExtract()
    # Section ends at the next *different* subject's heading (some subjects repeat their heading).
    end = len(text)
    for h in HEADING.finditer(text, start + 1):
        if not re.match(_pattern(subject), h.group(1).strip(), re.IGNORECASE):
            end = h.start()
            break
    end = min(end, start + chars)
    section = text[start:end]

    # Scanned pages (e.g. the Punjabi syllabus, printed in Shahmukhi as images) carry almost no
    # text: send those pages as images so Claude can read them.
    section = re.sub(rf"(\s*\d*\s*{PAGE_HEADER})+\s*$", "", section)
    if len(re.sub(PAGE_HEADER, "", section).strip()) >= MIN_TEXT:
        return SyllabusExtract(text=section)
    offsets, pos = [], 0
    for p in pages:
        offsets.append(pos)
        pos += len(p) + 1
    page_of = lambda pos: max(i for i, o in enumerate(offsets) if o <= pos)
    first = page_of(start)
    # Run to the page where the next subject starts, and drop that page if the next subject is the
    # first thing on it (only the running header comes before it).
    last = page_of(max(end - 1, start))
    if last > first and not re.sub(PAGE_HEADER, "", text[offsets[last]:end]).strip(" \n0123456789"):
        last -= 1
    with pymupdf.open(stream=syllabus_pdf, filetype="pdf") as doc:
        span = [doc[i] for i in range(first, last + 1)]
        if not any(page.get_images() for page in span):
            return SyllabusExtract(text=section)     # genuinely short, like English Essay
        return SyllabusExtract(text=section, images=[p.get_pixmap(dpi=IMAGE_DPI).tobytes("png") for p in span])


def book_text(name: str, data: bytes) -> str:
    pages = pdf_pages(data)
    return "\n".join(f"[{name}, p. {i}]\n{t}" for i, t in enumerate(pages, 1))
