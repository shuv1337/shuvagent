"""``web_search`` — read-only web search with honest fallbacks."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from shuvagent.tools.types import GatedToolCall, ToolResult, ToolRisk, ToolSpec

NAME = "web_search"
DESCRIPTION = (
    "Search the web for current information. Uses DuckDuckGo first, optional "
    "Brave Search fallback, and Wikipedia as a zero-config last resort."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "search_query": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

Resolver = Callable[[str], Iterable[str]]


@dataclass(frozen=True)
class SearchConfig:
    enabled: bool = True
    brave_search_api_key: str = ""
    wikipedia_fallback_enabled: bool = True
    total_timeout_sec: float = 20.0
    page_fetch_timeout_sec: float = 8.0
    max_results: int = 3


class UrllibHttpClient:
    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        timeout = float(kwargs.get("timeout", 10.0))
        headers = dict(kwargs.get("headers", {}))
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status_code=response.status,
                content=response.read(),
                headers=dict(response.headers.items()),
            )


@dataclass
class HttpResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]

    def json(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.content.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def spec(
    *,
    http_client: Any | None = None,
    resolver: Resolver | None = None,
    config: SearchConfig | None = None,
    enabled: bool | None = None,
    web_search_enabled: bool | None = None,
    brave_search_api_key: str | None = None,
    brave_api_key: str | None = None,
    wikipedia_fallback_enabled: bool | None = None,
) -> ToolSpec:
    http = http_client or UrllibHttpClient()
    dns_resolver = resolver or _resolve_host
    cfg = config or SearchConfig()
    effective_enabled = enabled if enabled is not None else web_search_enabled
    if effective_enabled is not None:
        cfg = SearchConfig(
            enabled=effective_enabled,
            brave_search_api_key=cfg.brave_search_api_key,
            wikipedia_fallback_enabled=cfg.wikipedia_fallback_enabled,
            total_timeout_sec=cfg.total_timeout_sec,
            page_fetch_timeout_sec=cfg.page_fetch_timeout_sec,
            max_results=cfg.max_results,
        )
    effective_brave_key = (
        brave_search_api_key if brave_search_api_key is not None else brave_api_key
    )
    if effective_brave_key is not None:
        cfg = SearchConfig(
            enabled=cfg.enabled,
            brave_search_api_key=effective_brave_key,
            wikipedia_fallback_enabled=cfg.wikipedia_fallback_enabled,
            total_timeout_sec=cfg.total_timeout_sec,
            page_fetch_timeout_sec=cfg.page_fetch_timeout_sec,
            max_results=cfg.max_results,
        )
    if wikipedia_fallback_enabled is not None:
        cfg = SearchConfig(
            enabled=cfg.enabled,
            brave_search_api_key=cfg.brave_search_api_key,
            wikipedia_fallback_enabled=wikipedia_fallback_enabled,
            total_timeout_sec=cfg.total_timeout_sec,
            page_fetch_timeout_sec=cfg.page_fetch_timeout_sec,
            max_results=cfg.max_results,
        )

    def handler(call: GatedToolCall) -> ToolResult:
        query = _query_arg(call.arguments)
        if not cfg.enabled:
            return ToolResult.failure("web_search_disabled")
        if query is None:
            return ToolResult.failure("missing_query")
        deadline = time.monotonic() + cfg.total_timeout_sec
        try:
            return _search(query, http, dns_resolver, cfg, deadline)
        except TimeoutError:
            return ToolResult.failure("search_timeout")
        except SearchBlocked:
            return ToolResult.success(
                {
                    "reply_text": (
                        "Web search was blocked by the search provider's bot "
                        "or anomaly challenge. I do not have reliable search "
                        "results for that query."
                    ),
                    "provider": "duckduckgo",
                    "query": query,
                    "blocked": True,
                }
            )

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )


class SearchBlocked(RuntimeError):
    pass


def _search(
    query: str,
    http: Any,
    resolver: Resolver,
    cfg: SearchConfig,
    deadline: float,
) -> ToolResult:
    _ensure_time(deadline)
    instant = http.get(
        "https://api.duckduckgo.com/"
        f"?q={quote(query)}&format=json&no_html=1&skip_disambig=1",
        timeout=min(5.0, _remaining(deadline)),
    )
    if _is_bot_challenge(_body(instant)):
        raise SearchBlocked
    instant_json = _json(instant)
    abstract = str(instant_json.get("Abstract") or "").strip()
    if abstract:
        return ToolResult.success(
            {
                "reply_text": _format_results(
                    "duckduckgo_instant",
                    query,
                    [
                        {
                            "title": str(instant_json.get("Heading") or query),
                            "url": str(instant_json.get("AbstractURL") or ""),
                            "snippet": abstract,
                        }
                    ],
                ),
                "provider": "duckduckgo_instant",
                "query": query,
                "results": [
                    {
                        "title": str(instant_json.get("Heading") or query),
                        "url": str(instant_json.get("AbstractURL") or ""),
                        "snippet": abstract,
                    }
                ],
            }
        )

    blocked = False
    try:
        ddg_html = http.get(
            f"https://duckduckgo.com/html/?q={quote(query)}",
            timeout=min(5.0, _remaining(deadline)),
        )
        body = _body(ddg_html)
        if _is_bot_challenge(body):
            blocked = True
        else:
            links = _extract_links(body, resolver)[: cfg.max_results]
            pages = _fetch_pages(query, links, http, resolver, cfg, deadline)
            if pages:
                return _pages_result("duckduckgo", query, pages)
    except Exception as exc:
        blocked = isinstance(exc, SearchBlocked)

    if cfg.brave_search_api_key:
        _ensure_time(deadline)
        brave = http.get(
            f"https://api.search.brave.com/res/v1/web/search?q={quote(query)}",
            timeout=min(5.0, _remaining(deadline)),
            headers={"X-Subscription-Token": cfg.brave_search_api_key},
        )
        brave_links = _brave_links(_json(brave), resolver)[: cfg.max_results]
        pages = _fetch_pages(query, brave_links, http, resolver, cfg, deadline)
        if pages:
            return _pages_result("brave", query, pages)

    if cfg.wikipedia_fallback_enabled:
        wiki = _wikipedia(query, http, deadline)
        if wiki is not None:
            return ToolResult.success(
                {
                    "provider": "wikipedia",
                    "query": query,
                    "results": [wiki],
                }
            )

    if blocked:
        return ToolResult.failure("search_blocked")
    return ToolResult.failure("no_search_results")


def _fetch_pages(
    query: str,
    links: list[dict[str, str]],
    http: Any,
    resolver: Resolver,
    cfg: SearchConfig,
    deadline: float,
) -> list[dict[str, str]]:
    if not links:
        return []
    page_deadline = min(deadline, time.monotonic() + cfg.page_fetch_timeout_sec)
    with ThreadPoolExecutor(max_workers=min(3, len(links))) as executor:
        futures = [
            executor.submit(_fetch_one_page, query, link, http, resolver, page_deadline)
            for link in links[: cfg.max_results]
        ]
        done, _ = wait(futures, timeout=max(0.0, page_deadline - time.monotonic()))
    pages: list[dict[str, str]] = []
    for future in done:
        try:
            page = future.result(timeout=0)
        except Exception:
            continue
        if page is not None:
            pages.append(page)
    return pages


def _fetch_one_page(
    query: str,
    link: dict[str, str],
    http: Any,
    resolver: Resolver,
    deadline: float,
) -> dict[str, str] | None:
    url = link.get("url", "")
    if not _is_public_url(url, resolver=resolver):
        return None
    _ensure_time(deadline)
    response = http.get(url, timeout=min(5.0, _remaining(deadline)))
    if int(getattr(response, "status_code", 200)) >= 400:
        return None
    text = _extract_text(_body(response))
    if not _has_query_overlap(query, text):
        return None
    return {
        "title": link.get("title") or url,
        "url": url,
        "snippet": text[:1000],
    }


def _wikipedia(query: str, http: Any, deadline: float) -> dict[str, str] | None:
    _ensure_time(deadline)
    open_search = http.get(
        "https://en.wikipedia.org/w/api.php?action=opensearch&limit=1"
        f"&namespace=0&format=json&search={quote(query)}",
        timeout=min(5.0, _remaining(deadline)),
    )
    data = _json_or_list(open_search)
    title = ""
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        title = str(data[1][0]) if data[1] else ""
    if not title:
        return None
    _ensure_time(deadline)
    summary = http.get(
        "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title),
        timeout=min(5.0, _remaining(deadline)),
    )
    summary_json = _json(summary)
    extract = str(summary_json.get("extract") or "").strip()
    if not extract:
        return None
    urls = summary_json.get("content_urls", {})
    page_url = ""
    if isinstance(urls, dict):
        desktop = urls.get("desktop", {})
        if isinstance(desktop, dict):
            page_url = str(desktop.get("page") or "")
    return {
        "title": str(summary_json.get("title") or title),
        "url": page_url,
        "snippet": extract,
    }


def _pages_result(provider: str, query: str, pages: list[dict[str, str]]) -> ToolResult:
    return ToolResult.success(
        {
            "reply_text": _format_results(provider, query, pages),
            "provider": provider,
            "query": query,
            "results": pages,
        }
    )


def _query_arg(arguments: dict[str, Any]) -> str | None:
    value = arguments.get("query") or arguments.get("search_query")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _format_results(provider: str, query: str, pages: list[dict[str, str]]) -> str:
    lines = [f"Search results for {query} via {provider}:"]
    for page in pages:
        title = page.get("title", "")
        snippet = page.get("snippet", "")
        url = page.get("url", "")
        lines.append(f"- {title}: {snippet} ({url})")
    return "\n".join(lines)


def _extract_links(body: str, resolver: Resolver) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for href, title in re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        body,
        re.IGNORECASE | re.DOTALL,
    ):
        href = unescape(href)
        if not href.startswith("http"):
            continue
        if _is_public_url(href, resolver=resolver):
            links.append({"url": href, "title": _extract_text(title)[:120]})
    return links


def _brave_links(data: dict[str, Any], resolver: Resolver) -> list[dict[str, str]]:
    web = data.get("web", {})
    raw_results = web.get("results", []) if isinstance(web, dict) else []
    links: list[dict[str, str]] = []
    if not isinstance(raw_results, list):
        return links
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "")
        if _is_public_url(url, resolver=resolver):
            links.append({"url": url, "title": str(raw.get("title") or url)})
    return links


def _is_bot_challenge(body: str) -> bool:
    lowered = body.lower()
    return "anomaly-modal" in lowered or "anomaly.js" in lowered


def _extract_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _has_query_overlap(query: str, text: str) -> bool:
    query_tokens = _tokens(query)
    if not query_tokens:
        return False
    return bool(query_tokens & _tokens(text))


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text.lower())
        if token not in {"the", "and", "for", "with", "that", "this"}
    }


def _is_public_url(url: str, *, resolver: Resolver | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname
    addresses: Iterable[str]
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        addresses = (resolver or _resolve_host)(host)
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def _resolve_host(host: str) -> Iterable[str]:
    return {
        str(item[4][0])
        for item in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    }


def _json(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _json_or_list(response: Any) -> object:
    try:
        return response.json()
    except Exception:
        try:
            return json.loads(_body(response))
        except json.JSONDecodeError:
            return {}


def _body(response: Any) -> str:
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


def _ensure_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining
