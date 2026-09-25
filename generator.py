"""Builds the 5-6 page data bank with Claude + live web search."""

import os
from collections.abc import Iterator

import anthropic

from subjects import GUIDANCE

MODEL = os.environ.get("CSS_MODEL", "claude-opus-5")
MAX_CONTINUATIONS = 5

SYSTEM = """You are an expert CSS (Pakistan Central Superior Services) examination mentor and researcher.
You build a "data bank" on one topic that an aspirant can use to write top-scoring answers and essays.

Accuracy rules. These matter more than length:
- Every fact, figure, date and statistic must come from a source you actually found with web search/fetch
  or from the provided book text, and must carry an inline citation: a markdown link [Source, date](url)
  for web sources or (Book title, p. N) for provided book text. If you cannot source a number, leave it out.
- Prefer authoritative sources: Dawn (dawn.com) and other major Pakistani and international papers,
  Pakistan Economic Survey, SBP, PBS, ministries, UN agencies, World Bank, IMF, ADB, think tanks, journals.
- Quotes: only use quotations you found verbatim in a source, attributed to the speaker, with a link.
  Never invent or "reconstruct" quotes.
- Recommended books: take them from the FPSC syllabus text when it is provided. Name the specific
  chapters or themes relevant to this topic when you know them; otherwise say which aspect the book covers.
  If no syllabus text is provided, label books as "commonly used" rather than "FPSC recommended".
- Scholars and writers: summarise their arguments accurately and name the work. Do not attribute views to
  people unless you have a source.
- Be balanced on contested political questions. Present the main positions and evidence, then a reasoned view.

Format: Markdown, about 2,800 to 3,500 words (5 to 6 printed pages). Use these sections:
# <Topic>
Subject, how the topic maps to the FPSC syllabus section, and the date of preparation.
## 1. Thesis statement / central argument
## 2. Background and context
## 3. Key facts and figures   (a table: Indicator | Figure | Year | Source)
## 4. Core analysis   (political, economic, social, legal, strategic, international dimensions as relevant)
## 5. Arguments and counter-arguments   (or causes / challenges / impacts, whichever fits)
## 6. What scholars and analysts say   (writers, books, op-eds, including Dawn columnists)
## 7. Pakistan's perspective and case studies
## 8. Recent developments in <year>   (news and Dawn articles from that year, with dates)
## 9. Way forward / recommendations
## 10. Quotations for use in answers   (verified only)
## 11. Likely exam questions   (in the style of FPSC past papers)
## 12. Model answer outline   (outline for a 20-mark question or an essay on this topic)
## 13. References
   ### Recommended books (from the FPSC syllabus) with relevant chapters
   ### Articles and reports (full list of links used)

Write for a Pakistani CSS aspirant: clear, dense with usable material, no filler."""


ISSI_INSTRUCTIONS = """ISSI Issue Briefs: the Institute of Strategic Studies Islamabad (issi.org.pk) publishes short
"Issue Briefs" on foreign policy, security, regional and strategic questions. Search for briefs related to this
topic (e.g. search: site:issi.org.pk "Issue Brief" <topic keywords>; the index is at
https://issi.org.pk/category/issi-publications/issi-publications-articles/brief/) and fetch the most relevant ones.
If you find relevant briefs, add a section right after section 6:
## 6A. ISSI Issue Briefs
For each brief (up to 4, most recent first): title, author, date, 3-5 key arguments or findings, how to use it in an
answer, and the link. Use their arguments elsewhere in the document too, cited. If none are relevant, write one line
saying no relevant ISSI Issue Brief was found."""


def build_messages(subject: str, topic: str, year: int, syllabus: str, books: str,
                   issi: bool = True) -> list[dict]:
    content = []
    if syllabus:
        content.append({"type": "document", "title": f"FPSC syllabus extract: {subject}",
                        "source": {"type": "text", "media_type": "text/plain", "data": syllabus}})
    if books:
        content.append({"type": "document", "title": "Aspirant's own books and notes",
                        "source": {"type": "text", "media_type": "text/plain", "data": books}})
    request = (f"Subject: {subject}\nTopic: {topic}\nYear for recent developments and Dawn articles: {year}\n\n"
               "Research this topic with web search (search dawn.com specifically for this year) and build the data bank.")
    if subject in GUIDANCE:
        request += f"\n\nSubject-specific guidance: {GUIDANCE[subject]}"
    if issi:
        request += f"\n\n{ISSI_INSTRUCTIONS}"
    content.append({"type": "text", "text": request})
    return [{"role": "user", "content": content}]


def generate(subject: str, topic: str, year: int, syllabus: str = "", books: str = "",
             issi: bool = True, client: anthropic.Anthropic | None = None) -> Iterator[str]:
    """Yields the document's text as it streams. Raises RuntimeError if the request is declined."""
    client = client or anthropic.Anthropic()
    messages = build_messages(subject, topic, year, syllabus, books, issi)
    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 20,
         "user_location": {"type": "approximate", "country": "PK"}},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
    ]
    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=SYSTEM,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            yield from stream.text_stream
            final = stream.get_final_message()
        if final.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request. Try rephrasing the topic.")
        if final.stop_reason != "pause_turn":
            return
        # Server-side search loop paused: send the turn back unchanged and it resumes.
        messages = messages + [{"role": "assistant", "content": final.content}]
