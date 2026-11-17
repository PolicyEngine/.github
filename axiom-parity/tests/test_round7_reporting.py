import pytest
from test_check import run

from axiom_parity.render import markdown


@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_continuation_prose_notice_reaches_the_job_summary(hub, mode):
    report = run(
        hub,
        "axiom: The rest is queued:\n"
        "- rulespec-us#1416 queued\n"
        "- The rates are already encoded-correct: us:statutes/26/24/d",
        mode=mode,
    )
    assert not report.would_fail
    assert "`encoded-correct` here is not read as a claim" in markdown(report)
