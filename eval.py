"""
eval.py - end-to-end eval suite for the claim checker.

Sends real draft emails with planted false claims through the REAL Gemini model
and checks two things:
  - every planted lie is flagged (not_found or contradicted), never "supported"
  - every true claim is marked "supported", so honest emails aren't nagged

Run:  python eval.py          (needs GEMINI_API_KEY in .env or the environment)
Exit code is non-zero if any scenario fails, so CI can gate on it.
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import checker  # noqa: E402

PAUSE = int(os.getenv("EVAL_PAUSE", "6"))   # seconds between calls, for free-tier rate limits

RESUME = """Aarav Mehta
Backend Developer | Bengaluru

EXPERIENCE
Finly (fintech startup), Backend Developer, Jan 2024 to present
- Built payment reconciliation APIs in Python and FastAPI on PostgreSQL
- Cut p95 API latency by 40% by adding Redis caching
- Led a team of 3 engineers on the merchant dashboard
- Set up Docker and GitHub Actions CI for 6 services

Kredo, Software Engineer Intern, Jun 2023 to Dec 2023
- Built a React admin panel used by 25 support agents
- Automated KYC document checks, saving about 10k manual reviews a month

SKILLS
Python, FastAPI, PostgreSQL, Redis, Docker, GitHub Actions, React, TypeScript, AWS (EC2, S3)

EDUCATION
BCA, Christ University, Bengaluru, 2023"""

# (name, draft email, words that identify planted lies, words that identify true claims)
SCENARIOS = [
    ("honest email passes",
     "Hi Priya, at Finly I built payment reconciliation APIs in FastAPI and cut p95 latency by 40% "
     "with Redis caching. Can join immediately.",
     [], ["reconciliation", "40%"]),
    ("invented skill",
     "Hi, I run Kubernetes clusters in production and built reconciliation APIs in FastAPI at Finly.",
     ["kubernetes"], ["reconciliation"]),
    ("inflated metric",
     "At Finly I cut p95 API latency by 70% using Redis caching.",
     ["70%"], []),
    ("bigger team than the resume",
     "I led a team of 8 engineers on the merchant dashboard at Finly.",
     ["8 engineers"], []),
    ("wrong employer",
     "At Razorpay I built payment reconciliation APIs in Python.",
     ["razorpay"], []),
    ("upgraded degree",
     "I have a B.Tech in Computer Science from Christ University.",
     ["b.tech"], []),
    ("years of experience out of thin air",
     "I have 6 years of experience building backends in Python.",
     ["6 years"], []),
    ("intern made senior",
     "At Kredo I worked as a Senior Engineer and built a React admin panel used by 25 support agents.",
     ["senior"], ["25 support agents"]),
    ("number in a different format is still true",
     "At Kredo I automated KYC document checks, saving about 10,000 manual reviews a month.",
     [], ["10,000"]),
    ("only talks about the founder's company",
     "Hi Rohan, loved your post on scaling payouts. Your onboarding flow is the best I've seen. "
     "Free for a call this week?",
     [], []),
]


def matches(claim_text, word):
    return word.lower() in claim_text.lower()


def run(name, email, lies, truths):
    report = checker.check(RESUME, email)
    claims = report["claims"]
    problems = []
    for word in lies:
        hits = [c for c in claims if matches(c["claim"], word)]
        if not hits:
            problems.append(f"lie '{word}' was not picked up as a claim")
        elif any(c["status"] == "supported" for c in hits):
            problems.append(f"lie '{word}' was marked supported")
    for word in truths:
        if not any(matches(c["claim"], word) and c["status"] == "supported" for c in claims):
            problems.append(f"true claim '{word}' was not marked supported")
    if not lies and not truths and not report["ok"]:
        problems.append("flagged something in an email with no claims about the candidate")
    return problems, claims


print("Running eval...\n")
passed = 0
for name, email, lies, truths in SCENARIOS:
    try:
        problems, claims = run(name, email, lies, truths)
    except Exception as e:     # an API error counts as a failure, not a crash
        problems, claims = [f"error: {type(e).__name__}: {e}"], []
    ok = not problems
    passed += ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    for p in problems:
        print(f"      {p}")
    if not ok:
        for c in claims:
            print(f"      - {c['status']:<12} {c['claim']!r}")
    time.sleep(PAUSE)

print(f"\nSCORE: {passed}/{len(SCENARIOS)} scenarios passed")
sys.exit(0 if passed == len(SCENARIOS) else 1)
