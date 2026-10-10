"""Draft a dispatch-ready pe-parity issue for a citation nothing covers yet.

The draft uses the section headings the dispatch-ready lint looks for. What
the finder can't know (the blocker, final output names) is left as a TODO,
so an unfinished draft fails the lint instead of passing as ready.
"""

from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from .propose import Proposal, TestCase, document_of

TODO = "TODO"
OGL = "Contains public sector information licensed under the Open Government Licence v3.0."


def module_path_for(citation: str) -> str:
    """``us/statute/26/32/d`` -> ``us/statutes/26/32/d.yaml``; CFR gets ``<title>-cfr``."""
    juris, kind, *rest = citation.split("/")
    plural = {"statute": "statutes", "regulation": "regulations", "guidance": "policies", "policy": "policies"}.get(
        kind, kind
    )
    if juris == "us" and kind == "regulation" and rest and rest[0].isdigit():
        rest = [f"{rest[0]}-cfr", *rest[1:]]
    return f"{juris}/{plural}/{'/'.join(rest)}.yaml"


def _get(url: str, timeout: int = 20) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "policyengine-axiom-parity"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:  # noqa: BLE001 - a draft without law text is still useful
        return None


def fetch_law(url: str) -> tuple[str, str] | None:
    """(text, provenance) for legislation.gov.uk and eCFR sources; None otherwise."""
    if "legislation.gov.uk" in url:
        base = re.sub(r"/(?:data\.(?:xml|htm|html)|contents)?$", "", url.split("#")[0].rstrip("/"))
        raw = _get(base + "/data.xml")
        if not raw:
            return None
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return None
        ns = "{http://www.legislation.gov.uk/namespaces/legislation}"
        body = next((el for el in (root.find(f".//{ns}Body"), root.find(f".//{ns}Schedules")) if el is not None), root)
        parts = []
        for el in body.iter():
            if el.tag in (f"{ns}Text", f"{ns}Title", f"{ns}Pnumber"):
                t = " ".join("".join(el.itertext()).split())
                if t:
                    parts.append(t)
        text = " ".join(parts)
        return (text, f"legislation.gov.uk `{base}/data.xml`. {OGL}") if text else None
    m = re.search(r"ecfr\.gov/current/title-(\d+)/(?:.*/)?section-(\d+)\.([0-9A-Za-z-]+)", url)
    if m:
        title, part, sec = m.groups()
        api = f"https://www.ecfr.gov/api/renderer/v1/content/enforce/current/title-{title}?part={part}&section={part}.{sec}"
        raw = _get(api)
        if not raw:
            return None
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="replace")))
        text = " ".join(text.split())
        return (text, f"eCFR renderer API `{api}`") if text else None
    return None


def _quote(text: str, limit: int = 6000) -> str:
    text = text if len(text) <= limit else text[:limit] + " […]"
    return "\n".join(f"> {line}" for line in re.findall(r".{1,110}(?:\s|$)", text))


def draft_issue(
    group: list[Proposal],
    pe_repo: str,
    pe_pr: int | None,
    pe_title: str,
    pe_tests: list[TestCase],
    searched_ref: str,
    fetch: bool = True,
) -> str:
    """One issue per source document, covering every uncovered citation in it."""
    cites = [p.citation for p in group]
    document = document_of(cites[0])
    modules = [module_path_for(c) for c in cites]
    refs = [r for p in group for r in p.references]
    urls = sorted({r.url for r in refs})
    names = sorted({f"`{r.name}` ({r.kind})" for r in refs})
    pr = f"{pe_repo}#{pe_pr}" if pe_pr else pe_repo

    law_parts = []
    for p in group:
        law = None
        if fetch:
            for u in sorted({r.url for r in p.references}):
                law = fetch_law(u)
                if law:
                    break
        if law:
            law_parts.append(
                f"**`{p.citation}`**, fetched from {law[1]} Check it against the pinned corpus row before dispatch.\n\n{_quote(law[0])}"
            )
        else:
            law_parts.append(
                f"**`{p.citation}`**: {TODO}: quote the operative text from the corpus or the official source."
            )
    law_md = "\n\n".join(law_parts)

    outputs = "\n".join(f"{i}. {n}: {TODO} name the output in the law's terms." for i, n in enumerate(names, 1))
    tests = (
        "\n".join(
            f"- `{t.name}` (from `{t.file}`): inputs {', '.join(f'{k}={v}' for k, v in list(_flat(t.input).items())[:6])}; "
            f"expected {', '.join(f'{k}={v}' for k, v in list(_flat(t.output).items())[:4])}. Expected values come from "
            f"the same external source as the PolicyEngine test."
            for t in pe_tests[:8]
        )
        or f"- {TODO}: companion cases with expected values from the statute, official form or official calculator."
    )
    module_lines = "\n".join(f"- `{m}` for corpus citation `{c}`" for m, c in zip(modules, cites, strict=True))
    finding = (
        f"Encode {', '.join(cites)} from {document} as {', '.join(f'`{m}`' for m in modules)}. {pr} ({pe_title}) "
        f"changes {', '.join(names) or 'these provisions'}. State each required output below from the provision's own "
        f"terms, each with a verbatim proof excerpt from the corpus provision, and pass the companion cases below."
    )
    return f"""## Encoding debt

PolicyEngine parity for {pr}: {pe_title}. The PR changes {", ".join(names) or "provisions"} citing {", ".join(urls)}.

The parity finder searched TheAxiomFoundation rulespec `main` at `{searched_ref}`: no module cites {", ".join(f"`{c}`" for c in cites)}, and no open `pe-parity` issue does either. They all sit in `{document}`; encode the document's provisions together.

## Module and corpus

{module_lines}

## Law (verbatim)

{law_md}

## Required outputs

{outputs or f"1. {TODO}"}

## review_finding (paste as-is)

> {finding}

## Companion tests

{tests}

## Blocker

{TODO}: say why the signed encoder can't run now (corpus pin, encoder pin, waiver), or dispatch it. Check that every citation above is in the corpus release rulespec pins.
"""


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(_flat(v, key))
            else:
                out[key] = v
    return out
