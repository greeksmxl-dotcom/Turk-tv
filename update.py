#!/usr/bin/env python3
"""Conservative, multi-source public IPTV playlist refresher.

Keeps channel metadata/order, replaces only repeatedly failing streams with
same-channel candidates that pass repeated probes. GitHub Actions can run this.
"""
from __future__ import annotations

import concurrent.futures
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "kaynak.m3u"
OUTPUT = BASE / "turk-tv.m3u"
EXTERNAL = [
    "https://iptv-org.github.io/iptv/countries/tr.m3u",
    "https://iptv-org.github.io/iptv/languages/tur.m3u",
    "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "https://iptv-org.github.io/iptv/categories/news.m3u",
    "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8",
    "https://iptv-org.github.io/iptv/index.m3u",
]
UA = "Mozilla/5.0 (compatible; public-playlist-checker/2.0)"
TIMEOUT = 7
WORKERS = 12
MAX_PLAYLIST_BYTES = 35_000_000
MAX_CANDIDATES_PER_CHANNEL = 18


@dataclass
class Channel:
    info: str
    url: str
    extras: list[str]

    @property
    def name(self) -> str:
        return self.info.split(",", 1)[1].strip() if "," in self.info else ""

    @property
    def tvg_id(self) -> str:
        match = re.search(r'\btvg-id\s*=\s*"([^"]+)"', self.info, re.I)
        return match.group(1).casefold() if match else ""


def read_url(url: str, limit: int) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return response.read(limit), response.headers.get("Content-Type", "")


def parse_playlist(content: str) -> list[Channel]:
    result: list[Channel] = []
    info = None
    extras: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            info, extras = line, []
        elif info and line.startswith("#"):
            extras.append(line)
        elif info and line and not line.startswith("#"):
            if line.startswith(("https://", "http://")):
                result.append(Channel(info, line, extras))
            info, extras = None, []
    return result


def normalize(name: str) -> str:
    name = name.casefold().replace("ı", "i")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"\b(?:hd|fhd|sd|4k|uhd|tr|turkiye|turkey|live|alternatif|alternative|backup|yedek|\d{3,4}p)\b", " ", name)
    return re.sub(r"[^a-z0-9]+", "", name)


def probe(url: str) -> bool:
    """Check that a URL returns plausible HLS/media; not proof of TV playback."""
    try:
        if not url.startswith(("http://", "https://")):
            return False
        data, ctype = read_url(url, 65536)
        ct = ctype.lower()
        if "text/html" in ct or data.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            return False
        text = data.decode("utf-8", errors="replace")
        if "#EXTM3U" in text[:128] and "#EXT-X-" in text:
            return True
        if "video/mp2t" in ct or ("application/octet-stream" in ct and data[:1] == b"\x47"):
            return True
        return False
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def stable_probe(url: str) -> bool:
    if not probe(url):
        return False
    time.sleep(0.4)
    return probe(url)


def main() -> int:
    if not SOURCE.exists() and not OUTPUT.exists():
        print("ERROR: kaynak.m3u or turk-tv.m3u missing", file=sys.stderr)
        return 1
    original = SOURCE.read_text(encoding="utf-8-sig") if SOURCE.exists() else ""
    current_text = OUTPUT.read_text(encoding="utf-8-sig") if OUTPUT.exists() else original
    channels = parse_playlist(current_text)
    if not channels:
        print("ERROR: playlist is empty or invalid", file=sys.stderr)
        return 1

    alternatives: dict[str, list[Channel]] = {}
    def add_candidate(ch: Channel) -> None:
        alternatives.setdefault(normalize(ch.name), []).append(ch)

    for ch in parse_playlist(original):
        add_candidate(ch)

    # Download sources concurrently to avoid slowing the scheduled workflow.
    def fetch(source: str) -> tuple[str, list[Channel], str | None]:
        try:
            data, _ = read_url(source, MAX_PLAYLIST_BYTES)
            return source, parse_playlist(data.decode("utf-8-sig", errors="replace")), None
        except Exception as exc:
            return source, [], str(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(EXTERNAL), 6)) as pool:
        for source, found, error in pool.map(fetch, EXTERNAL):
            if error:
                print(f"WARN: alternative source unavailable: {source}: {error}", flush=True)
            else:
                for ch in found:
                    add_candidate(ch)
                print(f"Fetched {len(found)} candidates from {source}", flush=True)

    unique_urls = list(dict.fromkeys(ch.url for ch in channels))
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        checks = dict(zip(unique_urls, pool.map(probe, unique_urls)))
    failed = [ch for ch in channels if not checks[ch.url]]
    print(f"Checked {len(channels)} channels; {len(failed)} failed first probe", flush=True)

    replaced = 0
    unresolved = 0
    for ch in failed:
        if stable_probe(ch.url):
            continue
        key = normalize(ch.name)
        matches = alternatives.get(key, [])
        # A tvg-id mismatch is evidence that similarly named streams are different channels.
        options: list[str] = []
        for candidate in matches:
            if candidate.url == ch.url:
                continue
            if ch.tvg_id and candidate.tvg_id and ch.tvg_id != candidate.tvg_id:
                continue
            if candidate.url not in options:
                options.append(candidate.url)
        print(f"SEARCH {ch.name}: {len(options)} distinct alternatives", flush=True)
        new_url = next((url for url in options[:MAX_CANDIDATES_PER_CHANNEL] if stable_probe(url)), None)
        if new_url:
            print(f"REPLACED {ch.name}: {ch.url} -> {new_url}", flush=True)
            ch.url = new_url
            replaced += 1
        else:
            print(f"UNRESOLVED {ch.name}: retaining existing link", flush=True)
            unresolved += 1

    if replaced:
        lines = ["#EXTM3U"]
        for ch in channels:
            lines.extend([ch.info, *ch.extras, ch.url])
        OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif not OUTPUT.exists():
        OUTPUT.write_text(current_text, encoding="utf-8")
    print(f"Done: replaced={replaced}, unresolved={unresolved}, total={len(channels)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
