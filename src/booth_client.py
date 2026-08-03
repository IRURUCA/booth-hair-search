"""
BOOTH への礼儀正しいアクセスを一手に引き受けるクライアント。

CLAUDE.md のクロール約束事をここに集約する:
- 1〜2秒間隔、必ず直列（このモジュールは同時実行を一切しない）
- User-Agent に連絡先を明記
- robots.txt を尊重（/terms /carts /cart には触れない）
- 取得物は cache/ に保存し、再実行時はキャッシュを参照。同じURLを二度取らない
- エラー時は指数バックオフ、連続失敗で停止
- 商品ファイル本体は絶対に取得しない（このクライアントは HTML と画像しか扱わない）
"""
from __future__ import annotations

import hashlib
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

# --- 連絡先つき User-Agent（CLAUDE.md 厳守）---
CONTACT = "syon.dolphin@gmail.com"
USER_AGENT = (
    f"booth-hair-search-research/0.1 (feasibility study; contact: {CONTACT})"
)

# レート制御
MIN_INTERVAL = 1.0   # 秒。直近リクエストからの最小間隔
MAX_INTERVAL = 2.0   # 秒。ジッタの上限
MAX_RETRIES = 5
BACKOFF_BASE = 2.0
CONSECUTIVE_FAIL_LIMIT = 5  # これだけ連続で失敗したら止まって報告

# robots.txt が Disallow しているパス接頭辞（実取得に失敗した場合のフォールバック）
ROBOTS_DISALLOW = ("/terms", "/carts", "/cart")
ROBOTS_URL = "https://booth.pm/robots.txt"

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
HTML_CACHE = CACHE_DIR / "html"
THUMB_CACHE = CACHE_DIR / "thumbs"


class CrawlStop(Exception):
    """連続失敗で処理を止めるための例外。"""


class BoothClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_request_ts = 0.0
        self._consecutive_failures = 0
        HTML_CACHE.mkdir(parents=True, exist_ok=True)
        THUMB_CACHE.mkdir(parents=True, exist_ok=True)
        self._robots_disallow = self._fetch_robots_disallow()

    # --- robots.txt を実取得して Disallow 接頭辞を得る（失敗時はフォールバック）---
    def _fetch_robots_disallow(self) -> tuple[str, ...]:
        try:
            resp = self.session.get(ROBOTS_URL, timeout=15)
            if resp.status_code != 200:
                return ROBOTS_DISALLOW
            disallow: list[str] = []
            applies = False  # 直前の User-agent 群に * が含まれるか
            for raw in resp.text.splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key, value = key.strip().lower(), value.strip()
                if key == "user-agent":
                    applies = value == "*"
                elif key == "disallow" and applies and value:
                    disallow.append(value)
            # 空（＝全許可）もあり得るが、想定外の全消えはフォールバックの方が安全側
            return tuple(disallow) or ROBOTS_DISALLOW
        except requests.RequestException:
            return ROBOTS_DISALLOW

    # --- robots.txt チェック ---
    def _robots_allows(self, url: str) -> bool:
        path = urlparse(url).path
        return not any(path.startswith(p) for p in self._robots_disallow)

    # --- レート制御。直近リクエストから最低 MIN_INTERVAL 空ける ---
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_ts
        wait = random.uniform(MIN_INTERVAL, MAX_INTERVAL) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.time()

    @staticmethod
    def _cache_key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]

    # --- HTML 取得（キャッシュ優先）---
    def get_html(self, url: str, fresh: bool = False) -> str:
        """URL の内容を返す。通常はキャッシュ優先（同じURLを二度取らない）。

        fresh=True は鮮度が本質のURL（新着一覧・統計の再取得）用で、キャッシュを
        読まずに取得し直す（結果はキャッシュへ上書き保存）。レート制御・バックオフは
        通常時と同一で、負荷は増やさない。
        """
        if not self._robots_allows(url):
            raise ValueError(f"robots.txt disallows this URL: {url}")

        cache_file = HTML_CACHE / f"{self._cache_key(url)}.html"
        if not fresh and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        text = self._get_with_backoff(url).text
        cache_file.write_text(text, encoding="utf-8")
        return text

    # --- 画像取得（キャッシュ優先）。パスを返す ---
    def get_image(self, url: str, dest: Path) -> Path:
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        resp = self._get_with_backoff(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    # --- 指数バックオフつき GET。直列・レート制御込み ---
    def _get_with_backoff(self, url: str) -> requests.Response:
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                resp = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                self._log(f"  request error, retrying ({attempt+1}/{MAX_RETRIES}): {e}")
                time.sleep(BACKOFF_BASE ** attempt + random.random())
                continue
            if resp.status_code == 200:
                self._consecutive_failures = 0
                return resp
            # 429/5xx はリトライ対象
            if resp.status_code in (429, 500, 502, 503, 504):
                self._log(f"  HTTP {resp.status_code}, retrying ({attempt+1}/{MAX_RETRIES}): {url}")
                time.sleep(BACKOFF_BASE ** attempt + random.random())
                continue
            # 404 等はリトライしても無駄。連続失敗にも数えない（サーバー側の明確な回答）
            resp.raise_for_status()

        # ここに来たら失敗
        self._consecutive_failures += 1
        if self._consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
            raise CrawlStop(
                f"連続 {self._consecutive_failures} 件失敗。止まって報告します。最後のURL: {url}"
            )
        raise requests.RequestException(f"failed after {MAX_RETRIES} retries: {url}")

    @staticmethod
    def _log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)
