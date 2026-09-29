"""Download UN documents from the Official Document System (ODS), politely.

How this follows the rules in the README ("Terms of use"):

- Documents are fetched only on demand, one at a time.
- Every HTTP request, including each redirect hop, goes through the RateLimiter
  (at most 100 requests per 5 minutes, at least 3 seconds apart).
- HTTP 429 and Retry-After are honoured: we pause all requests for as long as the
  server asks, and give up rather than hammer the server.
- Every document is cached on disk (in the git-ignored data folder), so it is
  downloaded only once.
- Requests carry an honest User-Agent that names UNSpeaks.
- We never try to get around bot protection.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from . import config
from .rate_limiter import RateLimiter


# --- Errors (messages are written so they can be shown to users) ------------


class OdsError(Exception):
    """Base class for all problems with fetching a document from ODS."""


class InvalidRequestError(OdsError):
    """The symbol or language is not valid."""


class DocumentNotFoundError(OdsError):
    """ODS has no document for this symbol and language."""


class RateLimitedError(OdsError):
    """ODS asked us to slow down and we should not retry right now."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class OdsUnavailableError(OdsError):
    """ODS could not be reached, returned an error, or blocked the request."""


# --- Input checks ------------------------------------------------------------

# UN symbols use letters, digits and / . ( ) -, e.g. A/RES/78/1, S/RES/2720(2023),
# A/C.3/78/L.12/Rev.1. Whitespace is removed first ("S/RES/2720 (2023)" is fine).
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/.()\-]*$")
_MAX_SYMBOL_LENGTH = 80


def normalize_symbol(symbol: str) -> str:
    cleaned = re.sub(r"\s+", "", symbol or "")
    if (
        not cleaned
        or len(cleaned) > _MAX_SYMBOL_LENGTH
        or not _SYMBOL_PATTERN.match(cleaned)
        or "//" in cleaned
        or ".." in cleaned
    ):
        raise InvalidRequestError(
            f"'{symbol}' is not a valid UN document symbol. "
            "Symbols look like 'A/RES/78/1' or 'S/RES/2720(2023)'."
        )
    return cleaned


def normalize_language(language: str) -> str:
    code = (language or "").strip().lower()
    if code not in config.ODS_LANGUAGES:
        options = ", ".join(sorted(config.ODS_LANGUAGES))
        raise InvalidRequestError(f"Unsupported language '{language}'. Use one of: {options}.")
    return code


# --- Client --------------------------------------------------------------------


@dataclass(frozen=True)
class FetchedPdf:
    symbol: str
    language: str
    path: Path  # the cached PDF on disk
    source_url: str  # the URL the PDF was downloaded from
    fetched_at: str  # when it was downloaded (UTC, ISO 8601)
    from_cache: bool


class OdsClient:
    """Fetches PDFs from ODS by document symbol, with caching and rate limiting."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        limiter: RateLimiter | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = config.MAX_ATTEMPTS,
        max_wait: float = config.MAX_RETRY_WAIT_SECONDS,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else config.data_dir() / "cache" / "ods"
        self.limiter = limiter or RateLimiter(
            config.MAX_REQUESTS, config.WINDOW_SECONDS, config.MIN_INTERVAL_SECONDS
        )
        self.max_attempts = max_attempts
        self.max_wait = max_wait
        self._http = httpx.Client(
            headers={"User-Agent": config.user_agent(), "Accept": "application/pdf,*/*;q=0.8"},
            timeout=httpx.Timeout(
                config.READ_TIMEOUT_SECONDS, connect=config.CONNECT_TIMEOUT_SECONDS
            ),
            follow_redirects=False,  # we follow redirects ourselves, so each hop is rate-limited
            transport=transport,
        )

    # Context-manager support: `with OdsClient() as client: ...`
    def __enter__(self) -> OdsClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def cache_paths(self, symbol: str, language: str) -> tuple[Path, Path]:
        """Where a document and its metadata are cached, e.g. en/A_RES_78_1.pdf."""
        name = symbol.replace("/", "_")
        folder = self.cache_dir / language
        return folder / f"{name}.pdf", folder / f"{name}.json"

    def fetch_pdf(self, symbol: str, language: str = "en") -> FetchedPdf:
        """Return the PDF for `symbol` in `language`, downloading it only if not cached."""
        symbol = normalize_symbol(symbol)
        language = normalize_language(language)
        pdf_path, meta_path = self.cache_paths(symbol, language)

        if pdf_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return FetchedPdf(
                symbol, language, pdf_path, meta["source_url"], meta["fetched_at"], True
            )

        url = config.ODS_BASE_URL + config.ODS_SYMBOL_ENDPOINT
        params = {"s": symbol, "l": language, "t": "pdf"}
        try:
            response = self._get_following_redirects(url, params)
        except DocumentNotFoundError as exc:
            raise DocumentNotFoundError(
                f"No document found for '{symbol}' in language '{language}' ({exc})."
            ) from exc

        content = response.content
        if not content.startswith(b"%PDF"):
            content_type = response.headers.get("content-type", "unknown")
            raise DocumentNotFoundError(
                f"ODS did not return a PDF for '{symbol}' in language '{language}' "
                f"(got {content_type}). The symbol may not exist or may not be "
                "available in this language."
            )
        if len(content) > config.MAX_PDF_BYTES:
            raise OdsUnavailableError(f"The PDF for '{symbol}' is too large to process.")

        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        source_url = str(response.url)
        _write_atomically(pdf_path, content)
        meta = {
            "symbol": symbol,
            "language": language,
            "source_url": source_url,
            "fetched_at": fetched_at,
            "bytes": len(content),
        }
        _write_atomically(meta_path, json.dumps(meta, indent=2).encode("utf-8"))
        return FetchedPdf(symbol, language, pdf_path, source_url, fetched_at, False)

    # --- internals ---------------------------------------------------------------

    def _get_following_redirects(
        self, url: str, params: dict[str, str] | None, max_redirects: int = 5
    ) -> httpx.Response:
        for _ in range(max_redirects + 1):
            response = self._request(url, params)
            if not response.is_redirect:
                return response
            location = response.headers.get("location")
            if not location:
                raise OdsUnavailableError("ODS sent a redirect without a target address.")
            url = urljoin(str(response.url), location)
            params = None  # the redirect target already contains everything
            _check_un_host(url)
        raise OdsUnavailableError("ODS redirected too many times.")

    def _request(self, url: str, params: dict[str, str] | None) -> httpx.Response:
        """One GET request, rate-limited, with polite retries."""
        for attempt in range(1, self.max_attempts + 1):
            last_attempt = attempt == self.max_attempts
            self.limiter.acquire()
            try:
                response = self._http.get(url, params=params)
            except httpx.TimeoutException as exc:
                if last_attempt:
                    raise OdsUnavailableError("ODS did not respond in time. Try again later.") from exc
                self._pause(_backoff_seconds(attempt))
                continue
            except httpx.HTTPError as exc:
                raise OdsUnavailableError(f"Could not reach ODS ({exc}).") from exc

            status = response.status_code

            if status == 429:  # Too Many Requests: respect Retry-After
                wait = _retry_after_seconds(response) or _backoff_seconds(attempt)
                self.limiter.block_for(wait)
                if last_attempt or wait > self.max_wait:
                    raise RateLimitedError(
                        "ODS asked UNSpeaks to slow down (HTTP 429). "
                        f"Try again in about {math.ceil(wait)} seconds.",
                        retry_after=wait,
                    )
                continue  # limiter.acquire() waits until the pause is over

            if status == 202 and "x-amzn-waf-action" in response.headers:
                raise OdsUnavailableError(
                    "ODS answered with a bot-protection challenge (HTTP 202). "
                    "UNSpeaks does not try to get around this."
                )

            if status in (404, 410):
                raise DocumentNotFoundError(f"HTTP {status}")

            if status >= 500:
                if last_attempt:
                    raise OdsUnavailableError(f"ODS returned an error (HTTP {status}). Try again later.")
                wait = _retry_after_seconds(response) or _backoff_seconds(attempt)
                if wait > self.max_wait:
                    raise OdsUnavailableError(f"ODS is unavailable (HTTP {status}). Try again later.")
                self._pause(wait)
                continue

            if status >= 400:  # e.g. 403: don't retry
                raise OdsUnavailableError(f"ODS refused the request (HTTP {status}).")

            return response

        raise OdsUnavailableError("ODS could not be reached.")  # not normally reached

    def _pause(self, seconds: float) -> None:
        """Pause all requests (not just this one) for `seconds`."""
        self.limiter.block_for(min(seconds, self.max_wait))


# --- helpers -------------------------------------------------------------------


def _backoff_seconds(attempt: int) -> float:
    return 5.0 * 2 ** (attempt - 1)  # 5 s, 10 s, 20 s, ...


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Read Retry-After, which is either a number of seconds or an HTTP date."""
    value = response.headers.get("retry-after")
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _check_un_host(url: str) -> None:
    host = (urlsplit(url).hostname or "").lower()
    if host != "un.org" and not host.endswith(".un.org"):
        raise OdsUnavailableError(f"ODS redirected to an unexpected site ({host}); not following it.")


def _write_atomically(path: Path, data: bytes) -> None:
    """Write via a temporary file, so a crash never leaves a half-written cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
