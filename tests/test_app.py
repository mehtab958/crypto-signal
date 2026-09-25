import json

import anthropic
import httpx2
import pymupdf
import pytest

import generator
from pdf_export import to_pdf
from sources import book_text, syllabus_section


def make_pdf(pages):
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((50, 72), text, fontsize=9)
    return doc.tobytes()


def test_syllabus_section_picks_subject_heading_not_table_of_contents():
    pdf = make_pdf([
        "CONTENTS\nPakistan Affairs ........ 12\nCurrent Affairs ........ 15",
        "PAKISTAN AFFAIRS (100 MARKS)\nI. Ideology of Pakistan\nSuggested Readings\n1. Some Book",
        "CURRENT AFFAIRS (100 MARKS)\nI. Pakistan's domestic affairs",
    ])
    s = syllabus_section(pdf, "Pakistan Affairs").text
    assert s.startswith("PAKISTAN AFFAIRS (100 MARKS)") and "Suggested Readings" in s
    assert syllabus_section(pdf, "Zoology").text == ""


def test_book_text_has_page_markers():
    assert "[notes.pdf, p. 2]" in book_text("notes.pdf", make_pdf(["a", "b"]))


def test_pdf_export():
    assert to_pdf("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |", "T").startswith(b"%PDF")


def sse(message_events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in message_events)


def message_stream(text, stop_reason):
    msg = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
           "content": [], "stop_reason": None, "stop_sequence": None,
           "usage": {"input_tokens": 1, "output_tokens": 1}}
    return sse([
        {"type": "message_start", "message": msg},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
         "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ])


def fake_client(responses, captured):
    def handler(request):
        captured.append((dict(request.headers), json.loads(request.content)))
        return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                               text=responses[len(captured) - 1])
    return anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(
        transport=httpx2.MockTransport(handler)))


def test_request_shape_and_pause_turn_resume():
    captured = []
    client = fake_client([message_stream("Part one. ", "pause_turn"),
                          message_stream("Part two.", "end_turn")], captured)
    out = "".join(generator.generate("Current Affairs", "Water crisis", 2026, "SYL", "", client=client))
    assert out == "Part one. Part two."
    assert len(captured) == 2
    headers, body = captured[0]
    assert "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["model"] == "claude-opus-5" and body["fallbacks"] == "default"
    assert body["thinking"] == {"type": "adaptive"}
    assert {t["type"] for t in body["tools"]} == {"web_search_20260209", "web_fetch_20260209"}
    assert all("user_location" not in t for t in body["tools"])   # API rejects country "PK"
    assert body["messages"][0]["content"][0]["title"].startswith("FPSC syllabus extract")
    # resume request re-sends the paused assistant turn and no extra user message
    assert [m["role"] for m in captured[1][1]["messages"]] == ["user", "assistant"]


def test_refusal_raises():
    client = fake_client([message_stream("", "refusal")], [])
    with pytest.raises(RuntimeError):
        list(generator.generate("Pakistan Affairs", "x", 2026, client=client))


def test_syllabus_matches_and_or_ampersand():
    pdf = make_pdf(["ENGLISH (PRECIS AND COMPOSITION) (100 MARKS)\nI. Precis writing"])
    assert syllabus_section(pdf, "English (Precis & Composition)").text.startswith("ENGLISH (PRECIS AND")


def test_request_includes_subject_guidance_and_issi():
    content = generator.build_messages("Islamic Studies", "Zakat", 2026, "", "", issi=True)[0]["content"]
    text = content[-1]["text"]
    assert "sunnah.com" in text and "issi.org.pk" in text and "6A. ISSI Issue Briefs" in text
    text = generator.build_messages("Criminology", "Police reform", 2026, "", "", issi=False)[0]["content"][-1]["text"]
    assert "PPC" in text and "issi.org.pk" not in text


def test_every_menu_subject_resolves():
    from subjects import GUIDANCE, MY_COMPULSORY, MY_OPTIONAL
    assert set(MY_COMPULSORY + MY_OPTIONAL) <= set(GUIDANCE)


from pathlib import Path

FPSC = Path(__file__).parent.parent / "data" / "fpsc_syllabus.pdf"


@pytest.mark.skipif(not FPSC.exists(), reason="official syllabus PDF not present")
def test_official_syllabus_extracts_each_subject_and_stops_at_the_next():
    from subjects import MY_COMPULSORY, MY_OPTIONAL, SYLLABUS_LENGTH, SYLLABUS_NAME
    data = FPSC.read_bytes()
    for subject in MY_COMPULSORY + MY_OPTIONAL:
        name = SYLLABUS_NAME.get(subject, subject)
        ex = syllabus_section(data, name, SYLLABUS_LENGTH.get(name, 15000))
        assert ex.text.upper().startswith(name.upper().split(" (")[0].split(" &")[0]), subject
        import re
        from sources import HEADING, _pattern
        others = [h.group(1) for h in HEADING.finditer(ex.text)
                  if not re.match(_pattern(name), h.group(1).strip(), re.IGNORECASE)]
        assert not others, f"{subject} runs into {others}"
    pol = syllabus_section(data, "Political Science", 30000).text
    assert "PAPER-II" in pol.upper() and "Suggested Readings".lower() in pol.lower()
    assert len(syllabus_section(data, "Islamic Studies").text) > 4000    # repeated heading not a cut
    punjabi = syllabus_section(data, "Punjabi")
    assert len(punjabi.images) == 2 and all(i.startswith(b"\x89PNG") for i in punjabi.images)
    assert syllabus_section(data, "English Essay").images == []


def test_scanned_syllabus_pages_are_sent_as_images():
    content = generator.build_messages("Punjabi", "Waris Shah", 2026, "", "", syllabus_images=[b"png"])[0]["content"]
    assert content[1]["type"] == "image" and content[1]["source"]["media_type"] == "image/png"
