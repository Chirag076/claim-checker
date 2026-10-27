"""
app.py - web page and API for the claim checker.

    uvicorn app:app --reload        then open http://localhost:8000
"""
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()

import checker  # noqa: E402  (after load_dotenv so GEMINI_MODEL from .env is picked up)
import resume_text  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("claim-checker")

app = FastAPI(title="Claim Checker",
              description="Flags claims in a draft outreach email that the resume doesn't back up.")
PAGE = Path(__file__).parent / "static" / "index.html"

# The live demo spends a real Gemini key, so each visitor gets a few checks a minute.
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))
_recent = defaultdict(deque)


def allow(ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    hits = _recent[ip]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return False
    hits.append(now)
    return True


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")    # Render sits behind a proxy
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


class CheckRequest(BaseModel):
    resume: str = Field(description="The candidate's resume as plain text")
    email: str = Field(description="The draft outreach email")


@app.get("/", include_in_schema=False)
def page():
    return FileResponse(PAGE)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract")
def upload_resume(file: UploadFile = File(description="Resume as PDF, DOCX or TXT, up to 5 MB")):
    """Turn an uploaded resume into plain text for the resume box. No AI involved."""
    data = file.file.read(resume_text.MAX_BYTES + 1)     # read one byte past the limit to detect big files
    try:
        text = resume_text.extract_text(file.filename, data)
    except resume_text.ExtractError as e:
        raise HTTPException(e.status, str(e))
    log.info("extracted %d chars from a %s upload", len(text), os.path.splitext(file.filename or "")[1])
    return {"text": text, "chars": len(text)}


@app.post("/check")
def check(body: CheckRequest, request: Request):
    """Plain `def`, so FastAPI runs the slow model call in a worker thread."""
    if not allow(client_ip(request)):
        raise HTTPException(429, "Too many checks. Wait a minute and try again.")
    started = time.time()
    try:
        result = checker.check(body.resume, body.email)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except checker.TemporaryError as e:
        raise HTTPException(503, str(e))
    except Exception:
        log.exception("check failed")
        raise HTTPException(500, "Something went wrong. Try again.")
    log.info("checked %d claims in %.1fs: %s", len(result["claims"]), time.time() - started, result["counts"])
    return result
