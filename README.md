# CSS Data Bank

Type a CSS topic and get a **5-6 page PDF data bank**: thesis, background, a facts-and-figures table,
analysis, arguments and counter-arguments, views of scholars and columnists, recent Dawn coverage for
the chosen year, a way forward, verified quotations, likely exam questions, a model answer outline and
a reference list with links. Every fact carries a source link.

Built with Streamlit and Claude (`claude-opus-5`) with live web search.

## Subjects

The subject menu starts with your papers: English Essay, English (Precis & Composition), General Science & Ability,
Current Affairs, Pakistan Affairs, Islamic Studies, Political Science Paper I and II, Public Administration,
Gender Studies, Criminology and Punjabi. Each has its own instructions in `subjects.py`. For example:
- Essay gets outlines and thesis options.
- Precis gets rules, exercises and answer keys.
- GSA gets MCQs and worked solutions.
- Islamiat gets verified Quranic verses and Ahadith with references.
- Punjabi gets Shahmukhi verses with translations.

Every other FPSC subject is under "Other subject".

## How it gets its material

| Source | How |
|---|---|
| FPSC syllabus and recommended books | Reads the subject's section of the official FPSC syllabus PDF (`data/fpsc_syllabus.pdf` or uploaded in the app) |
| Internet, Dawn, reports, figures | Live web search and page fetch during generation, with links |
| ISSI Issue Briefs | When the topic is related, searches issi.org.pk Issue Briefs and adds a section with their key arguments and links (toggle in the app) |
| Your own books / notes | Optional PDF upload; cited as (Book, p. N) |

It does not have the text of the recommended books themselves, which are copyrighted. It points you to the
relevant books and chapters, and can quote from PDFs you upload.

## Set up from an iPhone (about 20 minutes)

1. **Get a Claude API key:** go to console.anthropic.com, sign up, add credit, then open API Keys and create a key.
2. **Put this code on GitHub:** create a new repository (for example `css-databank`) and upload these files.
   The official FPSC syllabus PDF is already included as `data/fpsc_syllabus.pdf`. Replace it if FPSC publishes a newer one.
3. **Deploy for free:** go to share.streamlit.io, sign in with GitHub, click Create app, pick the repository,
   and set the main file to `app.py`.
4. **Add secrets:** in the app's Settings, open Secrets and paste:
   ```
   ANTHROPIC_API_KEY = "sk-ant-..."
   APP_PASSWORD = "your-password"
   ```
   Set `APP_PASSWORD`: without it, anyone who finds the link can spend your API credit.
5. Open the app link in Safari, then tap Share and Add to Home Screen. It now opens like an app.

## Cost

Each data bank does 10-15 web searches and reads a lot of source text. Expect roughly **$0.50-$1.20 per file**
on `claude-opus-5`. Setting `CSS_MODEL = "claude-sonnet-5"` in Secrets costs less than half as much, with somewhat
less depth. Check your real cost in the Anthropic console after the first few files.

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
python -m pytest tests     # tests use a fake API, no key needed
```

## Always check

AI research can still get a number, date or quote wrong. Before using a figure or quotation in the exam,
tap its source link and confirm it.
