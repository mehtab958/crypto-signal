import io

from markdown_pdf import MarkdownPdf, Section

CSS = """
body { font-family: serif; font-size: 11pt; line-height: 1.45; }
h1 { font-size: 20pt; color: #0b3d2e; } h2 { font-size: 14pt; color: #0b3d2e; margin-top: 14pt; }
h3 { font-size: 12pt; } table { border-collapse: collapse; } td, th { border: 1px solid #999; padding: 3pt; }
a { color: #1a5fb4; } blockquote { color: #333; font-style: italic; }
"""


def to_pdf(markdown_text: str, title: str) -> bytes:
    pdf = MarkdownPdf(toc_level=2)
    pdf.meta["title"] = title
    pdf.add_section(Section(markdown_text, paper_size="A4"), user_css=CSS)
    buf = io.BytesIO()
    pdf.save_bytes(buf)
    return buf.getvalue()
