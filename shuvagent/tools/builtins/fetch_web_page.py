"""``fetch_web_page`` — fetch and extract text from a web page."""

from __future__ import annotations

import re
from html import unescape
from importlib import import_module
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from shuvagent.tools.builtins.web_search import _is_public_url
from shuvagent.tools.types import GatedToolCall, ToolResult, ToolRisk, ToolSpec

NAME = "fetch_web_page"
DESCRIPTION = (
    "Fetch and extract text content from a web page URL. "
    "Use this to read a specific page found via web_search or provided by the user."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "The URL to fetch content from"},
        "include_links": {
            "type": "boolean",
            "description": "Whether to include links found on the page",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}


class UrllibHttpClient:
    def get(self, url: str, **kwargs: Any) -> Any:
        timeout = float(kwargs.get("timeout", 10.0))
        with urlopen(Request(url), timeout=timeout) as response:
            return _HttpResponse(
                status_code=response.status,
                content=response.read(),
                url=response.url,
            )


class _HttpResponse:
    def __init__(self, status_code: int, content: bytes, url: str) -> None:
        self.status_code = status_code
        self.content = content
        self.url = url


def spec(
    *,
    http_client: object | None = None,
    max_chars: int = 50_000,
) -> ToolSpec:
    http = http_client or UrllibHttpClient()

    def handler(call: GatedToolCall) -> ToolResult:
        url = call.arguments.get("url")
        include_links = bool(call.arguments.get("include_links", False))
        if not isinstance(url, str) or not url.strip():
            return ToolResult.failure("missing_url")
        url = url.strip()
        if not _is_public_url(url):
            return ToolResult.failure("url_not_allowed")
        try:
            response = http.get(url, timeout=10.0)  # type: ignore[attr-defined]
        except Exception as exc:
            return ToolResult.failure(f"http_error: {exc}")
        if int(getattr(response, "status_code", 200)) >= 400:
            return ToolResult.failure(f"http_status_{response.status_code}")
        final_url = str(getattr(response, "url", "") or url)
        if not _is_public_url(final_url):
            return ToolResult.failure("redirect_url_not_allowed")

        html = _body(response)
        title, text, links = _extract_page(html, final_url)
        truncated = len(text) > max_chars
        text = text[:max_chars]
        parts = []
        if title:
            parts.append(f"Title: {title}")
        parts.append(text)
        if truncated:
            parts.append("[truncated]")
        if include_links and links:
            parts.append("Links found on page:")
            parts.extend(f"- {label}: {href}" for label, href in links[:50])
        return ToolResult.success(
            {
                "reply_text": "\n".join(part for part in parts if part),
                "title": title,
                "url": final_url,
                "truncated": truncated,
            }
        )

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )


def _body(response: Any) -> str:
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


def _extract_page(html: str, base_url: str) -> tuple[str, str, list[tuple[str, str]]]:
    try:
        BeautifulSoup = import_module("bs4").BeautifulSoup
    except Exception:
        return _extract_page_raw(html, base_url)

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "meta", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    text = "\n".join(_dedupe_consecutive(lines))
    links = []
    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True) or str(anchor["href"])
        links.append((label, urljoin(base_url, str(anchor["href"]))))
    return title, text, links


def _extract_page_raw(
    html: str, base_url: str
) -> tuple[str, str, list[tuple[str, str]]]:
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    title = _clean_text(title_match.group(1)) if title_match else ""
    links = [
        (_clean_text(label) or href, urljoin(base_url, unescape(href)))
        for href, label in re.findall(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
    ]
    html = re.sub(r"(?is)<(script|style|meta|noscript).*?>.*?</\1>", " ", html)
    text = _clean_text(html)
    return title, text, links


def _clean_text(value: str) -> str:
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _dedupe_consecutive(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return deduped
