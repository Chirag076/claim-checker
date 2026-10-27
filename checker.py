"""
checker.py - catches claims in a draft outreach email that the resume doesn't back up.

How it works:
1. The model reads the resume and the draft and lists every factual claim the
   draft makes about the candidate, with a verdict and an exact quote from the
   resume as evidence.
2. Code then checks the model's work instead of trusting it:
   - "supported" needs a quote that really appears in the resume. An invented
     or paraphrased quote is downgraded to "not_found".
   - every number in a supported claim must also appear in its quote
     ("5 years" is not backed by a line that says "2 years").
   - the company or project a claim is tied to must be in the resume
     ("At Razorpay I built X" fails even if the resume has X at another company).
   So the model can flag a claim on its own, but it can never clear one
   without evidence the code can find in the resume.
"""
import os
import re
import time
import unicodedata

from pydantic import BaseModel, Field

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_CHARS = 20_000
STATUSES = ("supported", "not_found", "contradicted")
RETRY_WAITS = [5, 15, 30]     # seconds before each retry of a temporary Gemini error

SYSTEM_PROMPT = """You check a job seeker's draft outreach email against their resume.

List every factual claim the email makes about the candidate: skills and tools, years of
experience, job titles, employers, projects, numbers and results, education.
Ignore greetings, opinions, statements about the recipient or their company, availability
("can join immediately"), and plans or offers ("I can build X for you").

For each claim, keep the email's own wording in "claim", one fact per claim. Never drop the
company, school or project a claim is tied to: "At Razorpay I built X" keeps "At Razorpay" in
the claim, and "Razorpay" goes in "where".
- status "supported": the resume states it. evidence = the shortest exact quote from the
  resume that proves it, copied character for character.
- status "contradicted": the resume says something different (another number, employer,
  title or degree). evidence = the exact conflicting quote from the resume.
- status "not_found": the resume does not mention it. evidence = "".

Be strict. Numbers must match exactly. Using a tool in one project does not support years of
experience with it. Working on a team does not support leading it.
reason: one short sentence a candidate would understand."""


class Claim(BaseModel):
    # Field order is the order the model writes them: find the evidence first, then decide.
    claim: str = Field(description="The claim in the email's own words")
    where: str = Field(default="", description="Company, school or project the email ties this claim to, "
                                               "in the email's words, or empty")
    evidence: str = Field(description="Exact quote from the resume, or empty")
    status: str = Field(description="supported, not_found or contradicted")
    reason: str = Field(description="One short sentence")


class Report(BaseModel):
    claims: list[Claim]


class TemporaryError(Exception):
    """Gemini is overloaded or rate limited even after retries."""


# ---------- deterministic checks ----------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", "•": " ", " ": " "})
_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}


def normalize(text: str) -> str:
    """Lowercase, straighten quotes and dashes, collapse whitespace and bullets."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).lower()
    text = re.sub(r"[*●▪]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _bare(text: str) -> str:
    """Letters and digits only, for a second, looser comparison."""
    return re.sub(r"[^a-z0-9]+", "", normalize(text))


def quote_in_resume(quote: str, resume: str) -> bool:
    if not quote.strip():
        return False
    if normalize(quote) in normalize(resume):
        return True
    bare = _bare(quote)
    return len(bare) >= 4 and bare in _bare(resume)


def numbers(text: str) -> set[str]:
    """Numbers in a piece of text, normalised: 'four' -> 4, '10,000' -> 10000, '10k' -> 10000."""
    text = normalize(text)
    text = re.sub(r"\b(" + "|".join(_WORDS) + r")\b", lambda m: _WORDS[m.group(1)], text)
    found = set()
    for value, suffix in re.findall(r"(\d+(?:[.,]\d+)*)(?:\s*(k)\b)?", text):
        value = value.replace(",", "")
        if suffix == "k":
            value = str(int(float(value) * 1000))
        if value.endswith(".0"):
            value = value[:-2]
        found.add(value)
    return found


def verify(claims: list[Claim], resume: str) -> list[dict]:
    """Re-check the model's verdicts against the resume text."""
    results = []
    for c in claims:
        status = c.status.strip().lower().replace(" ", "_")
        row = {"claim": c.claim.strip(), "status": status, "evidence": c.evidence.strip(),
               "reason": c.reason.strip(), "checked_by": "model"}
        if status not in STATUSES:
            row.update(status="not_found", reason="The checker couldn't verify this claim.",
                       checked_by="code")
        elif status == "supported":
            where = c.where.strip()
            if not quote_in_resume(row["evidence"], resume):
                row.update(status="not_found", evidence="", checked_by="code",
                           reason="The quoted evidence isn't in the resume.")
            elif where and not quote_in_resume(where, resume):
                row.update(status="not_found", checked_by="code",
                           reason=f"{where} isn't in the resume.")
            else:
                missing = numbers(row["claim"]) - numbers(row["evidence"])
                if missing:
                    row.update(status="not_found", checked_by="code",
                               reason=f"The resume line doesn't back the number(s) {', '.join(sorted(missing))}.")
        elif status == "contradicted" and row["evidence"] and not quote_in_resume(row["evidence"], resume):
            row["evidence"] = ""      # keep the flag, drop the made-up quote
        results.append(row)
    return results


# ---------- model call ----------

_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client


def is_temporary(err) -> bool:
    return getattr(err, "code", None) in (429, 500, 503)


def ask_gemini(resume: str, email: str, waits=RETRY_WAITS) -> Report:
    from google.genai import errors, types
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT, temperature=0,
        response_mime_type="application/json", response_schema=Report)
    contents = f"RESUME:\n{resume}\n\nDRAFT EMAIL:\n{email}"
    attempts = [0] + list(waits)
    for i, wait in enumerate(attempts):
        time.sleep(wait)
        try:
            response = _gemini().models.generate_content(model=MODEL, contents=contents, config=config)
            return response.parsed or Report.model_validate_json(response.text)
        except errors.APIError as e:
            if not is_temporary(e):
                raise
            if i == len(attempts) - 1:
                raise TemporaryError("The AI model is busy right now. Try again in a minute.") from e


# ---------- public entry point ----------

def check(resume: str, email: str, ask=None) -> dict:
    ask = ask or ask_gemini      # looked up at call time, so tests can swap in a fake model
    resume, email = (resume or "").strip(), (email or "").strip()
    if not resume or not email:
        raise ValueError("Paste both the resume and the draft email.")
    if len(resume) > MAX_CHARS or len(email) > MAX_CHARS:
        raise ValueError(f"Keep each text under {MAX_CHARS:,} characters.")
    claims = verify(ask(resume, email).claims, resume)
    counts = {s: sum(c["status"] == s for c in claims) for s in STATUSES}
    return {"ok": counts["not_found"] + counts["contradicted"] == 0, "counts": counts, "claims": claims}
