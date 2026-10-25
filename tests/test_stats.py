import pytest

from evals.stats import fmt, rate, wilson


def test_wilson_known_values():
    lo, hi = wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=1e-3)


def test_zero_trials():
    assert wilson(0, 0) == (0.0, 0.0)
    assert "0 trials" in fmt(rate(0, 0))


def test_fmt_shows_n_and_interval():
    text = fmt(rate(7, 10))
    assert text.startswith("7/10 = 70%") and "95% CI" in text
