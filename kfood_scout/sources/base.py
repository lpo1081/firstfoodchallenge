"""공통: HTTP 호출 + 디스크 캐시. 같은 요청은 한 번만 원천에 묻고 이후엔 캐시를 재사용한다."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"


def cached_get_json(url: str, params: dict | None = None, headers: dict | None = None,
                    sleep: float = 0.0, retries: int = 4, timeout: int = 60):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps([url, sorted((params or {}).items())]).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            path.write_text(json.dumps(data))
            if sleep:
                time.sleep(sleep)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET 실패: {url} {params} -> {last}")
