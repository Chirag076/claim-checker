"""A busy Gemini (503/429) is retried; real errors are not."""
from types import SimpleNamespace

import pytest
from google.genai import errors

import checker

GOOD = '{"claims": [{"claim": "Uses Python", "status": "supported", "evidence": "Python", "reason": "r"}]}'


class FlakyModels:
    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(parsed=None, text=GOOD)


@pytest.fixture
def models(monkeypatch):
    def install(*failures):
        m = FlakyModels(failures)
        monkeypatch.setattr(checker, "_client", SimpleNamespace(models=m))
        return m
    return install


def busy():
    return errors.ServerError(503, {"error": {"message": "overloaded"}})


def test_retries_until_it_works(models):
    m = models(busy(), busy())
    report = checker.ask_gemini("cv", "email", waits=[0, 0, 0])
    assert m.calls == 3
    assert report.claims[0].claim == "Uses Python"


def test_gives_up_with_a_friendly_error(models):
    m = models(busy(), busy(), busy())
    with pytest.raises(checker.TemporaryError):
        checker.ask_gemini("cv", "email", waits=[0, 0])
    assert m.calls == 3


def test_real_errors_are_not_retried(models):
    m = models(errors.ClientError(400, {"error": {"message": "bad request"}}))
    with pytest.raises(errors.ClientError):
        checker.ask_gemini("cv", "email", waits=[0, 0])
    assert m.calls == 1
