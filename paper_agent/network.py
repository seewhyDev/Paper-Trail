"""Bounded, repository-only HTTP client. No model-controlled arbitrary URLs."""
import json
import os
import time
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from filelock import FileLock


class SourceError(Exception):
    pass


ALLOWED_HOSTS = {"export.arxiv.org", "arxiv.org", "www.ebi.ac.uk", "api.crossref.org"}


def check_url(url: str):
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or u.username or u.password
            or u.port not in (None, 443)):
        raise SourceError("원문 주소가 허용된 공개 저장소 경로가 아닙니다.")


class Network:
    def __init__(self, timeout=20, retries=1, transport=None, rate_dir: Path | None = None):
        self.timeout, self.retries, self.rate_dir = timeout, retries, rate_dir
        self.client = httpx.Client(transport=transport, follow_redirects=False, trust_env=False)
        self.last = {}
        self.deadline = float("inf")
        self.requests = 0

    def close(self):
        self.client.close()

    def _sleep(self, seconds: float):
        if seconds > 0:
            if time.monotonic() + seconds >= self.deadline:
                raise SourceError("네트워크 대기 중 실행 시간 상한에 도달했습니다.")
            time.sleep(seconds)

    def _throttle(self, host):
        key = "arxiv" if "arxiv.org" in host else host
        interval = 3.1 if key == "arxiv" else 1.0
        def update(last):
            self._sleep(max(0, interval - (time.time() - last.get(key, 0))))
            last[key] = time.time()
        if self.rate_dir:
            self.rate_dir.mkdir(parents=True, exist_ok=True)
            path = self.rate_dir / "rate.json"
            with FileLock(str(path) + ".lock", timeout=self.timeout):
                try:
                    last = json.loads(path.read_text())
                except (OSError, ValueError):
                    last = {}
                update(last)
                path.write_text(json.dumps(last))
        else:
            update(self.last)

    def get(self, url: str, params=None, max_bytes=12_000_000) -> tuple[bytes, str]:
        check_url(url)
        # Hold one cross-process arXiv connection at a time, even when scripts and UI coexist.
        lock = (FileLock(str(self.rate_dir / "arxiv-connection.lock"), timeout=self.timeout)
                if self.rate_dir and "arxiv.org" in urlsplit(url).hostname else nullcontext())
        if self.rate_dir:
            self.rate_dir.mkdir(parents=True, exist_ok=True)
        with lock:
            return self._get(url, params, max_bytes)

    def _get(self, url, params, max_bytes):
        target = str(httpx.URL(url, params=params))
        contact = os.getenv("PAPER_AGENT_CONTACT", "")
        headers = {"User-Agent": "PaperTrail/0.1 (local research" + ("; " + contact if contact else "") + ")"}
        for attempt in range(self.retries + 1):
            try:
                current = target
                for redirect in range(4):
                    check_url(current)
                    callback = getattr(self, "on_request", None)
                    if callback:
                        # The UI needs the public endpoint, never contact/query parameters.
                        callback(urlsplit(current)._replace(query="", fragment="").geturl())
                    self._throttle(urlsplit(current).hostname)
                    remaining = self.deadline - time.monotonic()
                    if remaining <= 0:
                        raise SourceError("실행 시간 상한")
                    self.requests += 1
                    with self.client.stream("GET", current, headers=headers,
                                            timeout=min(self.timeout, remaining)) as response:
                        if response.is_redirect:
                            current = urljoin(current, response.headers.get("location", ""))
                            continue
                        if response.status_code in (429, 500, 502, 503, 504):
                            if attempt == self.retries:
                                raise SourceError(f"HTTP {response.status_code}: 제한된 재시도 소진")
                            delay = response.headers.get("retry-after", "")
                            # Do not retry earlier than a server-requested long delay.
                            if delay and (not delay.isdigit() or int(delay) > 15):
                                raise SourceError("서버가 긴 대기를 요청했습니다. 이번 조회는 중단합니다.")
                            self._sleep(max(2 ** attempt, int(delay or 0)))
                            break
                        if response.status_code >= 400:
                            raise SourceError(f"HTTP {response.status_code}: 공개 자료 조회 실패")
                        content = bytearray()
                        for block in response.iter_bytes():
                            if time.monotonic() >= self.deadline:
                                raise SourceError("다운로드 시간 상한")
                            content.extend(block)
                            if len(content) > max_bytes:
                                raise SourceError("원문 크기 상한 12 MB 초과")
                        return bytes(content), current
                else:
                    raise SourceError("리다이렉트 상한 초과")
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == self.retries:
                    raise SourceError("네트워크 연결/시간초과: 제한된 재시도 소진") from None
                self._sleep(2 ** attempt)
        raise SourceError("네트워크 조회 실패")
