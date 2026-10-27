"""The code checks must catch a model that clears claims without real evidence. No API key needed."""
import pytest

import checker
from checker import Claim, Report

RESUME = """Aarav Mehta
Finly, Backend Developer, Jan 2024 to present
- Cut p95 API latency by 40% by adding Redis caching
- Led a team of four engineers on the merchant dashboard
- Processed 10,000 payouts a day
SKILLS: Python, FastAPI, PostgreSQL"""


def fake(*claims):
    """A stand-in for the model that returns exactly these verdicts."""
    return lambda resume, email: Report(claims=[Claim(**c) for c in claims])


def claim(text, status="supported", evidence="", reason="r"):
    return {"claim": text, "status": status, "evidence": evidence, "reason": reason}


def run(*claims):
    return checker.check(RESUME, "draft email", ask=fake(*claims))


def test_real_quote_stays_supported():
    out = run(claim("Cut latency by 40%", evidence="Cut p95 API latency by 40%"))
    assert out["claims"][0]["status"] == "supported"
    assert out["claims"][0]["checked_by"] == "model"
    assert out["ok"] is True


def test_invented_quote_is_downgraded():
    out = run(claim("Knows Kubernetes", evidence="Ran Kubernetes clusters in production"))
    c = out["claims"][0]
    assert c["status"] == "not_found"
    assert c["checked_by"] == "code"
    assert c["evidence"] == ""
    assert out["ok"] is False


def test_number_not_in_quote_is_downgraded():
    out = run(claim("Cut latency by 60%", evidence="Cut p95 API latency by 40%"))
    c = out["claims"][0]
    assert c["status"] == "not_found"
    assert "60" in c["reason"]


def test_years_not_backed_by_a_skills_line():
    out = run(claim("5 years of Python", evidence="Python"))
    assert out["claims"][0]["status"] == "not_found"


def test_number_words_match_digits():
    out = run(claim("Led a team of 4 engineers", evidence="Led a team of four engineers"))
    assert out["claims"][0]["status"] == "supported"


@pytest.mark.parametrize("text", ["10000 payouts a day", "10k payouts a day", "10,000 payouts daily"])
def test_number_formats_match(text):
    out = run(claim(text, evidence="Processed 10,000 payouts a day"))
    assert out["claims"][0]["status"] == "supported"


def test_quote_matching_ignores_case_spacing_and_curly_quotes():
    out = run(claim("Built with FastAPI", evidence="skills:  python, FASTAPI"))
    assert out["claims"][0]["status"] == "supported"


def test_contradiction_keeps_flag_but_drops_fake_quote():
    out = run(claim("Works at Google", status="contradicted", evidence="Google, SWE 2022"))
    c = out["claims"][0]
    assert c["status"] == "contradicted"
    assert c["evidence"] == ""


def test_claim_tied_to_a_company_not_in_resume_is_downgraded():
    # Found by the eval: the model dropped "At Razorpay" and approved the rest.
    out = run({**claim("At Razorpay I built reconciliation APIs", evidence="SKILLS: Python, FastAPI"),
               "where": "Razorpay"})
    c = out["claims"][0]
    assert c["status"] == "not_found"
    assert c["checked_by"] == "code"
    assert "Razorpay" in c["reason"]


def test_claim_tied_to_a_company_in_resume_stays_supported():
    out = run({**claim("At Finly I cut latency by 40%", evidence="Cut p95 API latency by 40%"),
               "where": "Finly"})
    assert out["claims"][0]["status"] == "supported"


def test_unknown_status_counts_as_not_found():
    out = run(claim("Something", status="probably true", evidence="Python"))
    assert out["claims"][0]["status"] == "not_found"


def test_counts_and_ok_flag():
    out = run(
        claim("Uses Python", evidence="Python"),
        claim("Knows Go", status="not_found"),
        claim("Led 6 people", status="contradicted", evidence="Led a team of four engineers"),
    )
    assert out["counts"] == {"supported": 1, "not_found": 1, "contradicted": 1}
    assert out["ok"] is False


def test_no_claims_is_ok():
    assert run()["ok"] is True


@pytest.mark.parametrize("resume,email", [("", "hi"), ("cv", ""), ("   ", "  ")])
def test_empty_input_is_rejected(resume, email):
    with pytest.raises(ValueError):
        checker.check(resume, email, ask=fake())


def test_long_input_is_rejected():
    with pytest.raises(ValueError):
        checker.check("x" * (checker.MAX_CHARS + 1), "hi", ask=fake())


def test_numbers_helper():
    assert checker.numbers("cut 3x, team of four, 1.3 years, 40%") == {"3", "4", "1.3", "40"}
