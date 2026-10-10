"""Map a reference URL to an Axiom corpus citation path.

The grammar comes from the ``corpus_citation_path`` values RuleSpec modules
actually carry (about 19,000 in rulespec-us and rulespec-uk on 2026-10-10):

- US Code: ``us/statute/<title>/<section>[/<subsection>...]``
  (``us/statute/26/151/d/5``);
- CFR: ``us/regulation/<title>/<part>/<section>[/...]``; 7 CFR 273.9 is
  ``us/regulation/7/273/9`` and 26 CFR 1.1401-1(d)(2)(i) is
  ``us/regulation/26/1/1401-1/d/2/i``;
- UK primary legislation: ``uk/statute/<type>/<year>/<number>/<section>``;
  secondary: ``uk/regulation/<type>/<year>/<number>/<regulation>``;
  schedules ``.../schedule/<n>/paragraph/<p>``, articles ``.../article/<n>``;
- GOV.UK guidance: ``uk/guidance/govuk/<slug>[/<page>]``;
- state statutes vary by state (``us-ca/statute/rtc/17041``,
  ``us-md/statute/gtg/10-709``, ``us-oh/statute/5747.02``). Where no exact
  rule is known, ``StateHint`` carries the state and section number so the
  index can match it against that state's citations.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

UK_PRIMARY = {
    "ukpga",
    "asp",
    "anaw",
    "asc",
    "nia",
    "ukla",
    "ukcm",
    "mwa",
    "apni",
    "aep",
    "aosp",
    "aip",
    "apgb",
    "gbla",
    "ukppa",
}
UK_SECONDARY = {
    "uksi",
    "ssi",
    "wsi",
    "nisr",
    "nisi",
    "ukmo",
    "uksro",
    "ssro",
    "nisro",
    "ukci",
    "ukdsi",
    "sdsi",
    "wdsi",
    "nidsr",
}


@dataclass(frozen=True)
class Citation:
    path: str  # corpus citation path
    source: str  # which rule produced it
    exact: bool = True  # False for a heuristic hint


@dataclass(frozen=True)
class StateHint:
    """A state source with no exact grammar: match by section number."""

    jurisdiction: str  # "us-ny"
    section: str  # "606"
    source: str


def _fragment_parts(fragment: str) -> list[str]:
    """``#i_2`` -> ["i", "2"]; ``#p-273.9(d)(5)`` -> ["d", "5"]; ``#c_1_A_ii`` -> [...]."""
    if not fragment:
        return []
    paren = re.findall(r"\(([A-Za-z0-9]+)\)", fragment)
    if paren:
        return paren
    frag = re.sub(r"^(?:p-|section-|subsection-|para-)", "", fragment)
    if re.fullmatch(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*", frag):
        return frag.split("_")
    return []


def _usc(title: str, section: str, fragment: str = "") -> Citation:
    parts = [p for p in _fragment_parts(fragment)]
    return Citation("/".join(["us/statute", title, section.lower() if section.isalpha() else section, *parts]), "usc")


def _cfr(title: str, section: str, fragment: str = "") -> Citation | None:
    if "." not in section:
        return None
    part, sec = section.split(".", 1)
    parts = _fragment_parts(fragment)
    return Citation("/".join(["us/regulation", title, part, sec, *parts]), "cfr")


def _legislation_gov_uk(path: str) -> Citation | None:
    segs = [s for s in path.strip("/").split("/") if s]
    if len(segs) < 3:
        return None
    kind, year, number = segs[0], segs[1], segs[2]
    if kind in UK_PRIMARY:
        root = "uk/statute"
    elif kind in UK_SECONDARY:
        root = "uk/regulation"
    else:
        return None
    if not re.fullmatch(r"\d{4}|[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", year) or not re.fullmatch(r"\d+", number):
        return None
    rest = segs[3:]
    # Drop version and format suffixes: /2024-04-06, /enacted, /made, /data.xml, /contents.
    clean: list[str] = []
    for s in rest:
        if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}|enacted|made|contents|data\.(?:xml|htm|html|pdf)|\w+\.pdf|prospective|crossheading|crossheading-.*",
            s,
        ):
            break
        clean.append(s)
    out = [root, kind, year, number]
    i = 0
    while i < len(clean):
        key = clean[i]
        val = clean[i + 1] if i + 1 < len(clean) else None
        if key in ("section", "regulation", "rule") and val:
            out.append(val)
            out.extend(clean[i + 2 :])
            break
        if key in ("schedule", "article", "paragraph", "part", "chapter") and val:
            out.extend([key, val])
            i += 2
            continue
        if key == "schedule" and val is None:
            out.append("schedule")
            break
        out.append(key)
        i += 1
    return Citation("/".join(out), "legislation.gov.uk")


def _gov_uk(path: str) -> Citation | None:
    segs = [s for s in path.strip("/").split("/") if s]
    if not segs or segs[0] in ("government", "guidance") and len(segs) < 2:
        return None
    if segs[0] in ("government", "search", "browse"):
        # Publications and policy papers are not corpus guidance pages.
        return None
    if segs[0] == "guidance":
        segs = segs[1:]
    return Citation("uk/guidance/govuk/" + "/".join(segs), "gov.uk")


_USC_GRANULE = re.compile(r"USC-(?:prelim-)?title(\d+)-section([0-9A-Za-z-]+)", re.IGNORECASE)
_GOVINFO_USC = re.compile(
    r"USCODE-\d{4}-title(\d+)/[^/]*?USCODE-\d{4}-title\d+-[^/]*?sec([0-9A-Za-z-]+)", re.IGNORECASE
)
_GOVINFO_CFR = re.compile(r"CFR-\d{4}-title(\d+)-vol\d+-sec(\d+[-.]?[0-9A-Za-z-]*)", re.IGNORECASE)


def map_url(url: str) -> Citation | StateHint | None:
    """Map one reference URL; None when the URL names no corpus source."""
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = urllib.parse.unquote(parsed.path)
    query = urllib.parse.parse_qs(parsed.query)
    frag = urllib.parse.unquote(parsed.fragment)

    if host == "legislation.gov.uk":
        return _legislation_gov_uk(path)
    if host == "gov.uk":
        return _gov_uk(path)

    if host == "law.cornell.edu":
        m = re.match(r"/uscode/text/(\d+)/([0-9A-Za-z-]+)", path)
        if m:
            return _usc(m.group(1), m.group(2), frag)
        m = re.match(r"/cfr/text/(\d+)/(\d+\.[0-9A-Za-z-]+)", path)
        if m:
            return _cfr(m.group(1), m.group(2), frag)
        return None
    if host == "uscode.house.gov":
        m = _USC_GRANULE.search(url)
        if m:
            return _usc(m.group(1), m.group(2), frag)
        return None
    if host == "govinfo.gov":
        m = _USC_GRANULE.search(url) or _GOVINFO_USC.search(url)
        if m:
            return _usc(m.group(1), m.group(2), frag)
        m = _GOVINFO_CFR.search(url)
        if m:
            return _cfr(m.group(1), m.group(2).replace("-", ".", 1) if "." not in m.group(2) else m.group(2), frag)
        return None
    if host == "ecfr.gov":
        m = re.search(r"/title-(\d+)/(?:.*/)?section-(\d+\.[0-9A-Za-z-]+)", path)
        if m:
            return _cfr(m.group(1), m.group(2), frag)
        m = re.search(r"/title-(\d+)/(?:.*/)?part-(\d+)(?:/|$)", path)
        if m and "section" in query:
            return _cfr(m.group(1), query["section"][0], frag)
        return None

    # California codes: codes_displaySection.xhtml?lawCode=RTC&sectionNum=17041
    if host == "leginfo.legislature.ca.gov":
        code = (query.get("lawCode") or [""])[0].lower()
        sec = (query.get("sectionNum") or [""])[0].rstrip(".")
        if code and sec:
            return Citation(f"us-ca/statute/{code}/{sec}", "ca-leginfo")
        return None
    # Maryland: mgaleg.maryland.gov/...?article=gtg&section=10-709
    if host == "mgaleg.maryland.gov":
        art = (query.get("article") or [""])[0].lower()
        sec = (query.get("section") or [""])[0]
        if art and sec:
            return Citation(f"us-md/statute/{art}/{sec}", "md-mgaleg")
        return None
    # Ohio: codes.ohio.gov/ohio-revised-code/section-5747.02
    if host == "codes.ohio.gov":
        m = re.search(r"/ohio-revised-code/section-([0-9.]+)", path)
        if m:
            return Citation(f"us-oh/statute/{m.group(1)}", "oh-codes")
        return None

    state = _STATE_HOSTS.get(host)
    if state:
        section = _section_token(path, query)
        if section:
            return StateHint(state, section, host)
    return None


def _section_token(path: str, query: dict[str, list[str]]) -> str | None:
    for key in ("section", "sectionNum", "SectionNumber", "sec", "statute", "num"):
        if key in query and query[key]:
            return query[key][0]
    tokens = re.findall(r"\d+[A-Za-z]?(?:[-.:]\d+[A-Za-z]?)+|\d{2,}[A-Za-z]?", path)
    return tokens[-1] if tokens else None


# State legislature and code hosts. A hit gives a StateHint, matched by
# section number against that state's corpus citations.
_STATE_HOSTS = {
    "nysenate.gov": "us-ny",
    "codes.findlaw.com": "",
    "revisor.mo.gov": "us-mo",
    "law.lis.virginia.gov": "us-va",
    "ncleg.gov": "us-nc",
    "legislature.mi.gov": "us-mi",
    "ilga.gov": "us-il",
    "malegislature.gov": "us-ma",
    "docs.legis.wisconsin.gov": "us-wi",
    "legislature.vermont.gov": "us-vt",
    "legislature.maine.gov": "us-me",
    "capitol.hawaii.gov": "us-hi",
    "data.capitol.hawaii.gov": "us-hi",
    "azleg.gov": "us-az",
    "leg.mt.gov": "us-mt",
    "iga.in.gov": "us-in",
    "legis.ga.gov": "us-ga",
    "oscn.net": "us-ok",
    "leg.colorado.gov": "us-co",
    "law.justia.com": "",
    "le.utah.gov": "us-ut",
    "legislature.idaho.gov": "us-id",
    "revisor.mn.gov": "us-mn",
    "legis.iowa.gov": "us-ia",
    "kslegislature.gov": "us-ks",
    "kslegislature.org": "us-ks",
    "apps.legislature.ky.gov": "us-ky",
    "legis.la.gov": "us-la",
    "legislature.la.gov": "us-la",
    "nebraskalegislature.gov": "us-ne",
    "leg.state.nv.us": "us-nv",
    "gencourt.state.nh.us": "us-nh",
    "nmlegis.gov": "us-nm",
    "legislature.nd.gov": "us-nd",
    "ndlegis.gov": "us-nd",
    "oregonlegislature.gov": "us-or",
    "legis.state.pa.us": "us-pa",
    "palegis.us": "us-pa",
    "webserver.rilegislature.gov": "us-ri",
    "rilegislature.gov": "us-ri",
    "scstatehouse.gov": "us-sc",
    "sdlegislature.gov": "us-sd",
    "capitol.tn.gov": "us-tn",
    "statutes.capitol.texas.gov": "us-tx",
    "app.leg.wa.gov": "us-wa",
    "code.wvlegislature.gov": "us-wv",
    "wyoleg.gov": "us-wy",
    "cga.ct.gov": "us-ct",
    "delcode.delaware.gov": "us-de",
    "flsenate.gov": "us-fl",
    "leg.state.fl.us": "us-fl",
    "alisondb.legislature.state.al.us": "us-al",
    "arkleg.state.ar.us": "us-ar",
    "akleg.gov": "us-ak",
    "code.dccouncil.gov": "us-dc",
    "code.dccouncil.us": "us-dc",
    "njleg.state.nj.us": "us-nj",
    "lis.njleg.state.nj.us": "us-nj",
    "pub.njleg.gov": "us-nj",
    "legislature.ms.gov": "us-ms",
}
_STATE_HOSTS = {k: v for k, v in _STATE_HOSTS.items() if v}


def map_urls(urls: list[str]) -> list[Citation | StateHint]:
    out: list[Citation | StateHint] = []
    seen: set = set()
    for url in urls:
        c = map_url(url)
        if c is not None and c not in seen:
            seen.add(c)
            out.append(c)
    return out
