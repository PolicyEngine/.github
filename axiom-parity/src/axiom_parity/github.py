"""A small GitHub REST client: just the reads the check needs.

It uses only the standard library so the check installs in seconds on a
runner. ``transport`` is injectable so tests run without network access.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Transport = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


class NotFound(Exception):
    """The resource does not exist, or the token cannot see it."""


class GitHubError(Exception):
    pass


def _urllib_transport(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers or {}), err.read() or b""
    except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as err:
        # A dropped connection is retried like a 503.
        return 599, {}, str(err).encode()


class GitHub:
    def __init__(
        self,
        token: str | None = None,
        api: str = "https://api.github.com",
        transport: Transport | None = None,
        retries: int = 3,
    ) -> None:
        self.token = token if token is not None else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
        self.api = api.rstrip("/")
        self.transport = transport or _urllib_transport
        self.retries = retries
        self.calls = 0
        self._cache: dict[str, Any] = {}

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "policyengine-axiom-parity",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, path: str, params: dict[str, Any] | None, accept: str) -> tuple[dict[str, str], bytes]:
        url = path if path.startswith("http") else f"{self.api}{path}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        key = f"{accept} {url}"
        if key in self._cache:
            return self._cache[key]
        for attempt in range(self.retries + 1):
            self.calls += 1
            status, headers, body = self.transport(url, self._headers(accept))
            if status == 404 or status == 410:
                raise NotFound(url)
            if status in (502, 503, 504, 599) or (status == 403 and b"secondary rate limit" in body.lower()):
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
            if status >= 400:
                raise GitHubError(f"GET {url} -> {status}: {body[:300]!r}")
            self._cache[key] = (headers, body)
            return headers, body
        raise GitHubError(f"GET {url} failed after retries")

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        _, body = self._request(path, params, "application/vnd.github+json")
        return json.loads(body or b"null")

    def get_raw(self, owner_repo: str, path: str, ref: str = "main") -> str:
        """Return a file's text at ``ref``; raise NotFound if it doesn't exist."""
        quoted = urllib.parse.quote(path)
        _, body = self._request(f"/repos/{owner_repo}/contents/{quoted}", {"ref": ref}, "application/vnd.github.raw")
        return body.decode("utf-8", errors="replace")

    def paginate(self, path: str, params: dict[str, Any] | None = None, limit: int = 3000) -> list[Any]:
        out: list[Any] = []
        page = 1
        params = dict(params or {})
        params.setdefault("per_page", 100)
        while len(out) < limit:
            params["page"] = page
            batch = self.get_json(path, params)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < params["per_page"]:
                break
            page += 1
        return out[:limit]

    def send_json(self, method: str, path: str, data: dict[str, Any]) -> Any:
        """POST or PATCH (comments only; the check itself never writes)."""
        url = path if path.startswith("http") else f"{self.api}{path}"
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            method=method,
            headers={**self._headers("application/vnd.github+json"), "Content-Type": "application/json"},
        )
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as err:
            raise GitHubError(f"{method} {url} -> {err.code}: {err.read()[:300]!r}") from err

    # Convenience reads -------------------------------------------------

    def issue(self, owner_repo: str, number: int) -> dict[str, Any]:
        """An issue or a PR (PRs carry a ``pull_request`` key)."""
        return self.get_json(f"/repos/{owner_repo}/issues/{number}")

    def issue_comments(self, owner_repo: str, number: int) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{owner_repo}/issues/{number}/comments")

    def pull(self, owner_repo: str, number: int) -> dict[str, Any]:
        return self.get_json(f"/repos/{owner_repo}/pulls/{number}")

    def pull_files(self, owner_repo: str, number: int) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{owner_repo}/pulls/{number}/files")

    def repo(self, owner_repo: str) -> dict[str, Any]:
        return self.get_json(f"/repos/{owner_repo}")

    def tree(self, owner_repo: str, ref: str = "main") -> list[str]:
        data = self.get_json(f"/repos/{owner_repo}/git/trees/{urllib.parse.quote(ref)}", {"recursive": "1"})
        return [e["path"] for e in data.get("tree", []) if e.get("type") == "blob"]
