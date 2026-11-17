"""Render a check report as a job summary and workflow annotations."""

from __future__ import annotations

from .check import ERROR, NOTICE, WARNING, Report

GUIDE = "https://github.com/PolicyEngine/.github/blob/main/CONTRIBUTING.md#mirror-policy-changes-in-axiom"


def verdict(report: Report) -> str:
    if not report.applies:
        return "Not required: this PR changes no parameters, variables or reforms."
    if report.would_fail and report.mode == "warn":
        return "Would fail (warn-only rollout: this check does not block merging yet)."
    if report.would_fail:
        return "Fail."
    return "Pass."


def markdown(report: Report) -> str:
    out = ["## Axiom parity", "", f"**{verdict(report)}**", ""]
    if report.policy_files:
        n = len(report.policy_files)
        shown = ", ".join(f"`{p}`" for p in report.policy_files[:8])
        more = f" and {n - 8} more" if n > 8 else ""
        out += [f"Policy files changed ({n}): {shown}{more}.", ""]
    for f in report.findings:
        out.append(f"- **{f.level}** ({f.code}): {f.message}")
    if report.findings:
        out.append("")
    if report.claims:
        out += ["| Claim | Result | Evidence and problems |", "|---|---|---|"]
        for c in report.claims:
            text = c.claim.text.replace("|", "\\|")
            if len(text) > 160:
                text = text[:159] + "…"
            if c.blocking:
                result = "would fail" if report.mode == "warn" else "fails"
            elif any(f.level == WARNING for f in c.findings):
                result = "ok, with warnings"
            else:
                result = "ok"
            notes = [e.replace("|", "\\|") for e in c.evidence]
            notes += [f"**{f.level}**: {f.message}".replace("|", "\\|") for f in c.findings]
            out.append(f"| `{c.claim.status}`: {text} | {result} | {'<br>'.join(notes) or '-'} |")
        out.append("")
    out.append(f"How to write the line: [CONTRIBUTING, Mirror policy changes in Axiom]({GUIDE}).")
    return "\n".join(out) + "\n"


def _escape(msg: str) -> str:
    return msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(report: Report) -> list[str]:
    """GitHub workflow commands (``::error::...``) for each finding."""
    out = []
    level_cmd = {ERROR: "error", WARNING: "warning", NOTICE: "notice"}
    for f in report.findings:
        out.append(f"::{level_cmd[f.level]} title=Axiom parity ({f.code})::{_escape(f.message)}")
    for c in report.claims:
        for f in c.findings:
            out.append(
                f"::{level_cmd[f.level]} title=Axiom parity ({f.code})::{_escape(c.claim.status + ': ' + f.message)}"
            )
    return out
