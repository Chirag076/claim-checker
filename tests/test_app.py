"""The API returns checked claims, explains bad input and limits each visitor's checks."""
import pytest
from fastapi.testclient import TestClient

import app as app_module
import checker
from checker import Claim, Report

BODY = {"resume": "Skills: Python, FastAPI", "email": "I know Python and Go."}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(checker, "ask_gemini", lambda resume, email: Report(claims=[
        Claim(claim="Knows Python", status="supported", evidence="Python", reason="Listed in skills"),
        Claim(claim="Knows Go", status="not_found", evidence="", reason="Not in the resume"),
    ]))
    app_module._recent.clear()
    return TestClient(app_module.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_serves_the_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Claim Checker" in r.text


def test_check_returns_verdicts(client):
    r = client.post("/check", json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["counts"] == {"supported": 1, "not_found": 1, "contradicted": 0}
    assert [c["claim"] for c in data["claims"]] == ["Knows Python", "Knows Go"]


def test_empty_input_explains_the_problem(client):
    r = client.post("/check", json={"resume": " ", "email": "hi"})
    assert r.status_code == 422
    assert "Paste both" in r.json()["detail"]


def test_busy_model_returns_503(client, monkeypatch):
    def busy(resume, email):
        raise checker.TemporaryError("The AI model is busy right now.")
    monkeypatch.setattr(checker, "ask_gemini", busy)
    r = client.post("/check", json=BODY)
    assert r.status_code == 503


def test_unexpected_error_is_hidden(client, monkeypatch):
    def broken(resume, email):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(checker, "ask_gemini", broken)
    r = client.post("/check", json=BODY)
    assert r.status_code == 500
    assert "secret" not in r.text


def test_rate_limit_per_visitor(client):
    headers = {"x-forwarded-for": "1.2.3.4"}
    codes = [client.post("/check", json=BODY, headers=headers).status_code
             for _ in range(app_module.RATE_LIMIT + 1)]
    assert codes[:-1] == [200] * app_module.RATE_LIMIT
    assert codes[-1] == 429
    # someone else is not affected
    assert client.post("/check", json=BODY, headers={"x-forwarded-for": "5.6.7.8"}).status_code == 200


def test_rate_limit_window_resets():
    app_module._recent.clear()
    for _ in range(app_module.RATE_LIMIT):
        assert app_module.allow("9.9.9.9", now=1000)
    assert not app_module.allow("9.9.9.9", now=1030)
    assert app_module.allow("9.9.9.9", now=1061)
