"""CSS subjects. Detailed topics and recommended books come from FPSC's official syllabus PDF
(data/fpsc_syllabus.pdf or uploaded in the app), not from here."""

MY_COMPULSORY = [
    "English Essay",
    "English (Precis & Composition)",
    "General Science & Ability",
    "Current Affairs",
    "Pakistan Affairs",
    "Islamic Studies",
]

MY_OPTIONAL = [
    "Political Science Paper I",
    "Political Science Paper II",
    "Public Administration",
    "Gender Studies",
    "Criminology",
    "Punjabi",
]

OTHER_SUBJECTS = [
    "Comparative Study of Major Religions", "Accountancy & Auditing", "Economics", "Computer Science",
    "International Relations", "Physics", "Chemistry", "Applied Mathematics", "Pure Mathematics",
    "Statistics", "Geology", "Business Administration", "Governance & Public Policies",
    "Town Planning & Urban Management", "History of Pakistan & India", "Islamic History & Culture",
    "British History", "European History", "History of USA", "Environmental Sciences",
    "Agriculture & Forestry", "Botany", "Zoology", "English Literature", "Urdu Literature", "Law",
    "Constitutional Law", "International Law", "Muslim Law & Jurisprudence", "Mercantile Law",
    "Philosophy", "Journalism & Mass Communication", "Psychology", "Geography", "Sociology",
    "Anthropology", "Sindhi", "Pashto", "Balochi", "Persian", "Arabic",
]

# Name to look for in the syllabus PDF, when it differs from the menu name.
SYLLABUS_NAME = {
    "Political Science Paper I": "Political Science",
    "Political Science Paper II": "Political Science",
}

# Two-paper subjects need a longer syllabus extract.
SYLLABUS_LENGTH = {"Political Science": 30000}

# What a useful data bank looks like differs by paper; this is appended to the request.
GUIDANCE = {
    "English Essay": (
        "Focus on essay material: 2-3 alternative thesis statements, a full essay outline (introduction, "
        "8-12 argument headings with evidence under each, counter-arguments and rebuttals, conclusion), "
        "strong opening and closing lines, and cross-disciplinary examples (history, philosophy, economics, "
        "literature). Include past CSS essay titles on similar themes."),
    "English (Precis & Composition)": (
        "This paper tests language skills, not a subject. If the topic is a skill (precis, comprehension, "
        "grammar, correction of sentences, pairs of words, idioms, direct/indirect speech, punctuation, "
        "translation), replace the 13 sections with: the rules, worked examples, common mistakes, "
        "practice exercises with an answer key, and past CSS paper questions. Skip the facts/figures and "
        "Dawn sections unless the topic is a composition theme."),
    "General Science & Ability": (
        "Explain the science clearly for a non-science student, with definitions, how it works, "
        "applications and Pakistan-related examples. Add 10 MCQs with answers. If the topic is from the "
        "Ability part (arithmetic, algebra, geometry, statistics, logical reasoning), give formulas, "
        "step-by-step worked examples and practice questions with solutions instead of news sections."),
    "Islamic Studies": (
        "Quote Quranic verses in Arabic with translation and reference (Surah name and number: ayah) and "
        "Ahadith with collection and number (e.g. Sahih Bukhari 6018). Use only verses and Ahadith you have "
        "verified from a reliable source such as quran.com or sunnah.com, and link it. Include views of "
        "classical and modern Muslim scholars and the contemporary relevance to Pakistan."),
    "Pakistan Affairs": (
        "Cover the historical background from the freedom movement where relevant, constitutional "
        "provisions (cite article numbers), and the views of historians such as those in the FPSC reading list."),
    "Current Affairs": (
        "Emphasise the latest developments, Pakistan's position and interests, the positions of key "
        "states and organisations, and official statements with dates."),
    "Political Science Paper I": (
        "Paper I covers political thought and theory. Present the thinkers' ideas accurately (Western and "
        "Muslim political thought), key concepts, criticisms, and relevance to modern states and Pakistan. "
        "Cite primary works."),
    "Political Science Paper II": (
        "Paper II covers comparative politics and political systems. Compare institutions across the "
        "systems in the syllabus with Pakistan, and cite constitutions by article where relevant."),
    "Public Administration": (
        "Cover administrative theories and theorists, then apply them to Pakistan: civil service structure "
        "and reforms, governance indicators, devolution and local government, accountability institutions, "
        "and reform commission reports."),
    "Gender Studies": (
        "Cover the feminist theories and theorists involved, international frameworks (CEDAW, SDG 5, Beijing "
        "Platform), Pakistan's laws and policies, indicators (e.g. WEF Global Gender Gap, PBS, UN Women data), "
        "and the women's movement in Pakistan."),
    "Criminology": (
        "Cover the criminological theories involved, the criminal justice system in Pakistan (police, "
        "prosecution, courts, prisons), relevant laws (PPC, CrPC, special laws, cite sections), crime "
        "statistics with sources, and comparative best practices."),
    "Punjabi": (
        "Cover poets, writers and literary movements with dates and major works. Quote verses in Punjabi "
        "(Shahmukhi script) with an English translation and the source. Include critical opinions of "
        "literary critics. Only quote verses you have verified from a reliable source."),
}
