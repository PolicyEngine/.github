"""Bounded round-8 clause oracle for the linear-scan differential property."""

import re

from axiom_parity.drain import (
    _DEFERRED_AFTER,
    _DEFERS,
    _IMPORT_DEFERRAL,
    _IMPORTS,
    _INTO,
    _LIST_GOES_ON,
    _MENTIONED_AFTER,
    _MENTIONS,
    _MODULE_NAME,
    _OTHER_VERBAL_CLAUSE,
    _PRECEDENT,
    _PRECEDENT_ANYWHERE,
    _REQUESTS,
    _SOURCE_CLAUSE,
    DEFERRED,
    IMPORT,
    MENTION,
    WORK,
    normal_module,
)

_CLAUSE_STARTS = re.compile(r"[,;]|\b(?:but|and|then)\b", re.I)


def _new_removal_clause(text: str) -> bool:
    """An explicit new predicate, rather than another removal object."""
    text = text.lstrip()
    return bool(
        _REQUESTS.match(text)
        or _SOURCE_CLAUSE.match(text)
        or _IMPORT_DEFERRAL.match(text)
        or _OTHER_VERBAL_CLAUSE.match(text)
    )


def _removal_request(text: str) -> bool:
    requests = list(_REQUESTS.finditer(text))
    return bool(requests and requests[-1].group(0).lower() in {"remove", "delete"})


def _closing_bracket(text: str, start: int) -> int | None:
    pairs = {"(": ")", "[": "]"}
    stack: list[str] = []
    for i in range(start, len(text)):
        if text[i] in pairs:
            stack.append(pairs[text[i]])
        elif stack and text[i] == stack[-1]:
            stack.pop()
            if not stack:
                return i
    return None


def _next_comma(text: str, start: int) -> int | None:
    depth = 0
    for i in range(start, len(text)):
        if text[i] in "([":
            depth += 1
        elif text[i] in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            if text[i] == ",":
                return i
            if text[i] == ";":
                break
    return None


def _own_clause(gap: str) -> str:
    """The module's governing clause, keeping a removal's objects and asides."""
    depth, i, lead = 0, 0, ""
    breaks = {m.start(): m for m in _CLAUSE_STARTS.finditer(gap)}
    while i < len(gap):
        ch = gap[i]
        if ch in "([":
            if _removal_request(lead):
                closing = _closing_bracket(gap, i)
                if closing is not None:
                    lead += " "
                    i = closing + 1
                    continue
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and i in breaks:
            boundary = breaks[i]
            removal = _removal_request(lead)
            following = gap[boundary.end() :].lstrip()
            if removal and ch == ",":
                closing = _next_comma(gap, boundary.end())
                if closing is not None:
                    continuation = gap[closing + 1 :].lstrip()
                    continuation = re.sub(r"^(?:and|or)\b\s*", "", continuation, flags=re.IGNORECASE)
                    # A paired aside can precede or follow coordinated objects.
                    # Its own verbs do not replace the governing removal.
                    if not _new_removal_clause(continuation):
                        lead += " "
                        i = closing + 1
                        continue
            # Adjectives such as "existing", "matching" and "deferred"
            # describe coordinated objects. Only a new predicate ends removal.
            if not (removal and boundary.group(0).lower() in {",", "and"} and not _new_removal_clause(following)):
                lead = ""
            else:
                lead += boundary.group(0)
            i = boundary.end()
            continue
        lead += ch
        i += 1
    return lead


_FROM = re.compile(r"\bfrom\b[^,;()]*$", re.I)


def _modules_in(sentence: str) -> list[tuple[str, str]]:
    """(module, WORK | IMPORT | MENTION | DEFERRED) for each module one sentence of plain text names.

    The words between the start of the module's own clause and the module
    decide: "import X", "do not import X", "mirroring the existing X". A list
    ("a.yaml, b.yaml and c.yaml") shares the first module's kind.
    """
    out: list[tuple[str, str]] = []
    last_end, kind = 0, WORK
    for m in _MODULE_NAME.finditer(sentence):
        if m.group("dir"):
            continue
        gap = sentence[last_end : m.start()]
        after = sentence[m.end() :]
        if out and _LIST_GOES_ON.match(gap):
            pass  # the list's first module decided
        else:
            # The module's own clause decides. A request in it makes the module work
            # unless what stands between the request and the module says otherwise.
            lead = _own_clause(gap)
            requests = list(_REQUESTS.finditer(lead))
            tail = lead[requests[-1].end() :] if requests else lead
            removal = requests and requests[-1].group(0).lower() in {"remove", "delete"}
            comparison = re.search(r"\bas\s*$", lead) and re.match(r"\s+(?:does|do|did)\b", after)
            # A "deferred dependency" can itself be the object removed. An
            # explicit refusal to import the module still gives a deferral.
            defers = _IMPORT_DEFERRAL if removal else _DEFERS
            if defers.search(tail) or _DEFERRED_AFTER.match(after):
                kind = DEFERRED
            elif _INTO.search(lead):
                kind = WORK
            elif removal and _FROM.search(tail):
                kind = WORK
            elif _IMPORTS.search(tail):
                kind = IMPORT
            elif requests:
                kind = MENTION if _PRECEDENT.search(tail) or comparison else WORK
            else:
                # "(X)" on its own is a pointer to where something lives.
                aside = lead.rstrip().endswith("(") and after.lstrip().startswith(")")
                described = _MENTIONS.search(lead.rstrip("( ") + " ") or _MENTIONED_AFTER.match(after)
                kind = MENTION if described or aside or _PRECEDENT_ANYWHERE.search(lead) else WORK
        out.append((normal_module(m.group(0)), kind))
        last_end = m.end()
    return out
