"""CSS Data Bank: type a topic, get a sourced 5-6 page PDF.   Run:  streamlit run app.py"""

import os
from datetime import date
from pathlib import Path

import anthropic
import streamlit as st

from generator import generate
from pdf_export import to_pdf
from sources import BOOKS_CHARS, SYLLABUS_CHARS, SyllabusExtract, book_text, syllabus_section
from subjects import MY_COMPULSORY, MY_OPTIONAL, OTHER_SUBJECTS, SYLLABUS_LENGTH, SYLLABUS_NAME

st.set_page_config(page_title="CSS Data Bank", page_icon="📚")

# Streamlit Cloud secrets -> environment, so the Anthropic client finds the key.
# Locally there may be no secrets file at all; plain environment variables work too.
try:
    secrets = dict(st.secrets)
except FileNotFoundError:
    secrets = {}
for key in ("ANTHROPIC_API_KEY", "APP_PASSWORD", "CSS_MODEL"):
    if key in secrets and key not in os.environ:
        os.environ[key] = str(secrets[key])

# Password gate: without it anyone with the link could spend your API credit.
password = os.environ.get("APP_PASSWORD")
if password and st.session_state.get("authed") is not True:
    if st.text_input("Password", type="password") == password:
        st.session_state.authed = True
        st.rerun()
    st.stop()

st.title("📚 CSS Data Bank")
st.caption("Type a topic, get a 5-6 page sourced PDF: facts, figures, arguments, analysts' views, "
           "Dawn articles, recommended books and a model answer outline.")

SYLLABUS_PATH = Path(__file__).parent / "data" / "fpsc_syllabus.pdf"
syllabus_pdf = SYLLABUS_PATH.read_bytes() if SYLLABUS_PATH.exists() else None

with st.sidebar:
    st.header("FPSC syllabus")
    if syllabus_pdf:
        st.success("Official syllabus loaded")
    else:
        up = st.file_uploader("Upload FPSC syllabus PDF (from fpsc.gov.pk)", type="pdf")
        if up:
            syllabus_pdf = up.getvalue()
        else:
            st.info("Without it, book lists are labelled 'commonly used' rather than 'FPSC recommended'.")
    st.header("Your books / notes (optional)")
    book_files = st.file_uploader("PDF chapters or notes to draw from", type="pdf", accept_multiple_files=True)

subject = st.selectbox("Subject", MY_COMPULSORY + MY_OPTIONAL + ["Other subject..."])
if subject == "Other subject...":
    subject = st.selectbox("Other subject", OTHER_SUBJECTS)
topic = st.text_input("Topic", placeholder="e.g. Water crisis in Pakistan")
year = st.number_input("Year for recent developments / Dawn articles", 2000, date.today().year,
                       date.today().year)
issi = st.checkbox("Include ISSI Issue Briefs when relevant", value=True,
                   help="Searches issi.org.pk for Issue Briefs on this topic and adds their key arguments.")

if st.button("Generate data bank", type="primary", disabled=not (topic and subject)):
    name = SYLLABUS_NAME.get(subject, subject)
    extract = (syllabus_section(syllabus_pdf, name, SYLLABUS_LENGTH.get(name, SYLLABUS_CHARS))
               if syllabus_pdf else SyllabusExtract())
    books = "\n\n".join(book_text(f.name, f.getvalue()) for f in book_files or [])[:BOOKS_CHARS]
    st.info("Researching and writing. This usually takes 2 to 5 minutes. Keep this page open.")
    try:
        text = st.write_stream(generate(subject, topic, int(year), extract.text, books, issi, extract.images))
    except anthropic.AuthenticationError:
        st.error("The API key is missing or invalid. Add ANTHROPIC_API_KEY in the app's secrets.")
        st.stop()
    except anthropic.RateLimitError:
        st.error("Rate limited by the API. Wait a minute and try again.")
        st.stop()
    except anthropic.APIConnectionError:
        st.error("Network error while contacting the API. Try again.")
        st.stop()
    except anthropic.APIStatusError as e:
        st.error(f"API error ({e.status_code}): {e.message}")
        st.stop()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()
    st.session_state.result = (topic, text)

if "result" in st.session_state:
    t, text = st.session_state.result
    st.download_button("⬇️ Download PDF", to_pdf(text, t), file_name=f"{t[:60]}.pdf",
                       mime="application/pdf", type="primary")
    st.warning("Check key figures and quotes against the linked sources before using them in the exam.")
