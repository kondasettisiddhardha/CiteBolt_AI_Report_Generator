"""Research Agent.

Searches the web for the topic, collects 5-8 sources, and stores title, URL and
key content in the shared state. Tavily is used when a key is present; otherwise
the agent falls back to DuckDuckGo. Every search is retried before giving up.
"""

import logging
import time
from typing import Any

import httpx

from app.config import BACKOFF, RETRIES, TARGET_SOURCE_COUNT, TAVILY_API_KEY

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"

# Snippet length kept per source. Long enough to analyse, short enough to stay
# well inside the model's context window for six sources.
SNIPPET_CHARS = 1200


def _tavily_search(topic: str, limit: int) -> list[dict[str, str]]:
    """Query Tavily and normalise the response into source dicts."""
    response = httpx.post(
        TAVILY_URL,
        json={
            "api_key": TAVILY_API_KEY,
            "query": topic,
            "search_depth": "advanced",
            "max_results": limit,
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return [
        {
            "title": str(item.get("title") or "Untitled source"),
            "url": str(item.get("url") or ""),
            "content": str(item.get("content") or ""),
        }
        for item in payload.get("results", [])
    ]


def _duckduckgo_search(topic: str, limit: int) -> list[dict[str, str]]:
    """Query DuckDuckGo (no key required) and normalise the results.

    DuckDuckGo's HTML endpoint occasionally returns nothing for larger result
    counts, so the agent asks again with smaller pages and merges what it gets.
    """
    try:
        from ddgs import DDGS
    except ImportError as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "DuckDuckGo fallback needs the 'ddgs' package. Run: pip install -r requirements.txt"
        ) from exc

    collected: list[dict[str, str]] = []
    last_error: Exception | None = None

    for page_size in sorted({limit, min(limit, 6), TARGET_SOURCE_COUNT}, reverse=True):
        try:
            with DDGS() as ddgs:
                results = ddgs.text(topic, max_results=page_size)
        except Exception as exc:  # pragma: no cover - network
            last_error = exc
            logger.warning("DuckDuckGo page of %d failed: %s", page_size, exc)
            time.sleep(1.5)
            continue

        for item in results or []:
            collected.append(
                {
                    "title": str(item.get("title") or "Untitled source"),
                    "url": str(item.get("href") or ""),
                    "content": str(item.get("body") or ""),
                }
            )

        if len(collected) >= TARGET_SOURCE_COUNT:
            break
        time.sleep(1.0)

    if collected:
        return collected

    raise RuntimeError(
        f"DuckDuckGo returned no results ({last_error})" if last_error else "DuckDuckGo returned no results"
    )


def _collect_sources(topic: str) -> list[dict[str, str]]:
    """Search with Tavily, then DuckDuckGo, retrying each provider."""
    providers = []
    if TAVILY_API_KEY:
        providers.append(("Tavily", _tavily_search))
    providers.append(("DuckDuckGo", _duckduckgo_search))

    last_error: Exception | None = None
    for name, provider in providers:
        for attempt in range(1, RETRIES + 1):
            try:
                sources = provider(topic, TARGET_SOURCE_COUNT + 5)
                sources = _dedupe(sources)
                if sources:
                    sources = _verify_sources(sources)
                    logger.info("Research Agent collected %d sources via %s", len(sources), name)
                    return sources[: TARGET_SOURCE_COUNT + 3]
                raise RuntimeError("search returned no results")
            except Exception as exc:  # pragma: no cover - network
                last_error = exc
                logger.warning("%s attempt %d failed: %s", name, attempt, exc)
                if attempt < RETRIES:
                    time.sleep(BACKOFF * attempt)

    raise RuntimeError(f"All search providers failed: {last_error}")


def _dedupe(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop blank and duplicate URLs, and keep domains diverse."""
    seen_urls: set[str] = set()
    seen_domains: dict[str, int] = {}
    kept: list[dict[str, str]] = []

    for source in sources:
        url = source.get("url", "").strip()
        if not url or url in seen_urls:
            continue

        domain = url.split("//", 1)[-1].split("/", 1)[0].lower()
        # At most two results per site so one vendor can't dominate the sources.
        if seen_domains.get(domain, 0) >= 2:
            continue

        seen_urls.add(url)
        seen_domains[domain] = seen_domains.get(domain, 0) + 1
        source["content"] = source.get("content", "").strip()[:SNIPPET_CHARS]
        kept.append(source)

    return kept


def _reachable(url: str) -> bool:
    """Only keep URLs that actually load. Never invent or rewrite a URL."""
    if not url.startswith(("http://", "https://")):
        return False
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CiteBoltBot/1.0)"}
    for method in ("head", "get"):
        try:
            request = getattr(httpx, method)
            response = request(url, headers=headers, timeout=8.0, follow_redirects=True)
            if response.status_code == 200:
                return True
            if method == "head" and response.status_code in (403, 405, 501):
                continue
            return False
        except Exception:
            continue
    return False


def _verify_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    """Fetch each candidate URL and drop the ones that don't return 200."""
    verified: list[dict[str, str]] = []
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_reachable, [source["url"] for source in sources]))

    for source, ok in zip(sources, results):
        if ok:
            verified.append(source)
        else:
            logger.info("Dropping unreachable source: %s", source["url"])

    if verified:
        return verified
    # Never leave the pipeline with nothing because of a transient network issue.
    logger.warning("No source passed verification; keeping the search results")
    return sources


def research_node(state: dict[str, Any]) -> dict[str, Any]:
    """Collect sources and append them to the shared state."""
    topic = state.get("topic", "")
    if not topic:
        raise ValueError("Research Agent requires a topic")

    raw_sources = _collect_sources(topic)

    state["sources"] = [
        {
            "title": source["title"],
            "url": source["url"],
            "content": source["content"] or source["title"],
            "source_index": index,
        }
        for index, source in enumerate(raw_sources, start=1)
    ]
    return state
