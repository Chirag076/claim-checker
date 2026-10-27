# Claim Checker: catch made-up claims before an outreach email is sent

[![CI](https://github.com/Chirag076/claim-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/Chirag076/claim-checker/actions/workflows/ci.yml)

AI tools now write cold emails and job applications from a resume. When the model adds a skill the candidate doesn't have, inflates a number or upgrades a job title, the email still goes out under the candidate's name, and one false claim can cost them that founder or recruiter.

Claim Checker reads a resume (pasted, or uploaded as PDF, DOCX or TXT) and a draft email, lists every factual claim the email makes about the candidate, and marks each one **Supported**, **Not in resume** or **Contradicts resume**, with the exact resume line as evidence.

## Try it

Live at **https://claims.evrrun.com** (Render free tier: the first check can take up to a minute while the server wakes up). Click **Load example** to see it catch an inflated metric, an invented skill and an upgraded degree.

## How it works

```
Resume + draft email
        ↓
   Gemini (structured JSON output)
   lists claims, a verdict and an exact resume quote for each
        ↓
   Code re-checks every "supported" verdict
   - the quote must really be in the resume
   - every number in the claim must be in that quote
   - the company it's tied to must be in the resume
        ↓
   Supported / Not in resume / Contradicts resume
```

### The model can flag a claim, but it can't clear one without evidence

A model asked "is this claim in the resume?" will sometimes say yes and quote a line that doesn't exist, or match "led a team of 8" to a line that says 3. So the model's "supported" verdict is never trusted on its own:

- **The quote must exist.** The evidence is matched against the resume text (ignoring case, spacing, curly quotes and bullets). An invented or paraphrased quote downgrades the claim to *Not in resume*.
- **Numbers must match.** Every number in the claim must appear in the quoted line. "Four" matches 4 and "10k" matches 10,000, but "cut latency by 60%" is not backed by a line that says 40%.
- **The company must match.** The model reports which company, school or project each claim is tied to, and that name must be in the resume. "At Razorpay I built reconciliation APIs" fails even when the resume has reconciliation APIs at another company. The eval suite found this one: the model had dropped "At Razorpay" and approved the rest of the sentence.
- **Unknown verdicts fail closed.** Anything other than the three statuses counts as *Not in resume*.

The page shows "(caught by the code check)" whenever the code overruled the model.

### Resume upload

Upload or drop a PDF, DOCX or TXT resume (up to 5 MB) and `POST /extract` turns it into text with pypdf or python-docx, including resumes built from Word tables. No AI is involved, and the text lands in the resume box so the candidate can see exactly what the checker compares against and fix anything the conversion got wrong. Scanned PDFs with no text layer, password-protected files and unsupported types get a clear message instead of a silent empty box.

## Testing

Both layers run in [GitHub Actions](.github/workflows/ci.yml) on every push.

**1. Unit tests** (`tests/`, 42 tests, no API key needed): invented quotes, number mismatches, claims tied to a company that isn't in the resume, PDF/DOCX/TXT uploads (scanned, corrupt, oversized and wrong-type files), number formats ("four", "10k", "10,000"), quote normalisation, contradictions, bad input, retrying a busy Gemini (503/429), hiding internal errors and the per-visitor rate limit.

```bash
pip install -r requirements-dev.txt
pytest -v
```

**2. Evals** (`eval.py`, 10 scenarios): real draft emails with planted lies sent through the real model. Covers an invented skill, an inflated metric, a bigger team, a wrong employer, an upgraded degree, made-up years of experience and an intern promoted to senior. It also checks the other direction: honest claims, and the same number written differently, must come back *Supported*, and an email with no claims about the candidate must not be flagged. Exits non-zero on any failure.

```bash
python eval.py
```

## Run it

```bash
git clone https://github.com/Chirag076/claim-checker.git
cd claim-checker
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` (see `.env.example`):

```
GEMINI_API_KEY=your_gemini_key
```

Start it and open http://localhost:8000:

```bash
uvicorn app:app --reload
```

API docs are at http://localhost:8000/docs.

```bash
curl -X POST http://localhost:8000/check -H "Content-Type: application/json" \
  -d '{"resume": "Skills: Python, FastAPI", "email": "I know Python and Kubernetes."}'
```

### Deploy

On [Render](https://render.com), choose **New > Blueprint**, pick this repo and paste your `GEMINI_API_KEY`. It reads `render.yaml`. Each visitor gets 5 checks a minute so the free Gemini quota isn't drained.

## Tech stack

- **Python**, **FastAPI**
- **Google Gemini** with structured JSON output (Pydantic schema)
- **pypdf** and **python-docx** for resume uploads
- **pytest** and **GitHub Actions**: unit tests and evals on every push
- **Render** free tier

## Next

- Suggest a corrected sentence for each flagged claim
- A browser extension that checks the draft inside Gmail before sending

## Contact

Built by **Chirag Chhabra**.

- Email: chiragchhabrahmo@gmail.com
- Portfolio: https://portfolio.evrrun.com
- GitHub: https://github.com/Chirag076
