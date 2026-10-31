#!/usr/bin/env python3
"""Conservative IPTV playlist refresh using publicly listed alternatives.

Inputs: kaynak.m3u (baseline), turk-tv.m3u (current)
Output: turk-tv.m3u, only when a confirmed replacement is available.
"""
from __future__ import annotations
import concurrent.futures
import os
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
EXTERNAL = ["https://iptv-org.github.io/iptv/countries/tr.m3u"]
UA = "Mozilla/5.0 (compatible; playlist-checker/1.0)"
TIMEOUT = 8
WORKERS = 10

@dataclass
class Channel:
    info: str
    url: str
    extras: list[str]

    @property
    def name(self):
        return self.info.split(",", 1)[1].strip() if "," in self.info else ""


def read_url(url: str, limit: int = 2_000_000) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return response.read(limit), response.headers.get("Content-Type", "")


def parse_playlist(content: str) -> list[Channel]:
    result = []
    info = None
    extras = []
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
    name = re.sub(r"\b(?:hd|fhd|sd|4k|uhd|tr|turkiye|turkey|live)\b", " ", name)
    return re.sub(r"[^a-z0-9]+", "", name)


def probe(url: str) -> bool:
    """Require HTTP success and a plausible HLS manifest or media stream.

    This is not a guarantee of actual TV playback.
    """
    try:
        if not url.startswith(("http://", "https://")):
            return False
        data, ctype = read_url(url, 65536)
        ct = ctype.lower()
        if "text/html" in ct or data.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            return False
        text = data[:65536].decode("utf-8", errors="replace")
        if "#EXTM3U" in text[:128] and ("#EXT-X-" in text or "#EXTINF:" in text):
            return True
        # Some channels provide MPEG-TS directly.
        if "video/mp2t" in ct or "application/octet-stream" in ct and data[:1] == b"\x47":
            return True
        return False
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def stable_probe(url: str) -> bool:
    if not probe(url):
        return False
    time.sleep(0.5)
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

    baseline = parse_playlist(original)
    alternatives: dict[str, list[str]] = {}
    for ch in baseline:
        alternatives.setdefault(normalize(ch.name), []).append(ch.url)
    for source in EXTERNAL:
        try:
            data, _ = read_url(source)
            found = parse_playlist(data.decode("utf-8-sig", errors="replace"))
            for ch in found:
                alternatives.setdefault(normalize(ch.name), []).append(ch.url)
            print(f"Fetched {len(found)} candidates from {source}")
        except Exception as exc:
            print(f"WARN: alternative source unavailable: {source}: {exc}")

    urls = list(dict.fromkeys(ch.url for ch in channels))
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        checks = dict(zip(urls, pool.map(probe, urls)))
    failed = [ch for ch in channels if not checks[ch.url]]
    print(f"Checked {len(channels)} channels; {len(failed)} failed first probe")

    # Verify failure before considering replacement (helps avoid transient failures).
    replaced = 0
    unresolved = 0
    for ch in failed:
        if stable_probe(ch.url):
            continue
        key = normalize(ch.name)
        options = list(dict.fromkeys(alternatives.get(key, [])))
        options = [u for u in options if u != ch.url]
        new_url = next((u for u in options if stable_probe(u)), None)
        if new_url:
            print(f"REPLACED {ch.name}: {ch.url} -> {new_url}")
            ch.url = new_url
            replaced += 1
        else:
            print(f"UNRESOLVED {ch.name}: retaining existing link")
            unresolved += 1

    lines = ["#EXTM3U"]
    for ch in channels:
        lines.extend([ch.info, *ch.extras, ch.url])
    updated = "\n".join(lines) + "\n"
    # Preserve existing formatting if nothing changed.
    if replaced:
        OUTPUT.write_text(updated, encoding="utf-8")
    elif not OUTPUT.exists():
        OUTPUT.write_text(current_text, encoding="utf-8")
    print(f"Done: replaced={replaced}, unresolved={unresolved}, total={len(channels)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
