#!/usr/bin/env python3
"""
Media Online Scraper untuk SIAP Analytics
Sumber: Google News RSS (Detik, Kompas, Tribun, CNN Indonesia, dll)
Tidak butuh akun, tidak ada rate limit Twitter.
"""
import sys
import re
import hashlib
from datetime import datetime
from email.utils import parsedate

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from .twitter import clean_text

# ── Sumber berita yang dicoba ─────────────────────────────────────────────────

DIRECT_SOURCES = [
    {
        "name":    "Detik.com",
        "search":  "https://www.detik.com/search/searchall?query={query}&sortby=time",
        "item":    "article.list-content__item",
        "title":   "h2.media__title a, h3.media__title a",
        "desc":    "div.media__desc",
        "date":    "div.media__date span",
    },
    {
        "name":    "Kompas.com",
        "search":  "https://search.kompas.com/search/?q={query}&sortby=score&st=all&site=kompas.com",
        "item":    "div.article__list",
        "title":   "h2.article__title a, h3.article__title a",
        "desc":    "p.article__lead",
        "date":    "div.article__date",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> tuple[str, str]:
    """Kembalikan (date_str, datetime_str) dari berbagai format."""
    now = datetime.now()
    try:
        t = parsedate(raw)
        if t:
            dt = datetime(*t[:6])
            return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S")


def _in_range(date_str: str, date_from: str | None, date_to: str | None) -> bool:
    if date_from and date_str < date_from:
        return False
    if date_to and date_str > date_to:
        return False
    return True


def _make_article(uid: str, user: str, title: str, desc: str,
                  date_str: str, dt_str: str, url: str) -> dict:
    text = f"{title}. {desc}".strip(". ")
    return {
        "id":         uid,
        "user":       user,
        "name":       title,
        "text":       text,
        "text_clean": clean_text(text),
        "date":       date_str,
        "datetime":   dt_str,
        "likes":      0,
        "retweets":   0,
        "replies":    0,
        "views":      0,
        "source":     "media_online",
        "sentiment":  None,
        "confidence": 0,
    }

# ── Google News RSS ───────────────────────────────────────────────────────────

def scrape_google_news(keywords: list, max_items: int = 100,
                       date_from: str | None = None,
                       date_to: str | None = None) -> list:
    if not HAS_FEEDPARSER:
        print("[!] feedparser tidak terinstall. Install: pip install feedparser")
        return []

    query = " ".join(keywords)
    quoted = requests.utils.quote(query) if HAS_REQUESTS else query.replace(" ", "+")
    url = (
        f"https://news.google.com/rss/search"
        f"?q={quoted}&hl=id-ID&gl=ID&ceid=ID:id"
    )

    print(f"  Google News RSS: '{query}'")
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"  [!] feedparser error: {e}")
        return []

    articles = []
    for entry in feed.entries:
        date_str, dt_str = _parse_date(entry.get("published", ""))
        if not _in_range(date_str, date_from, date_to):
            continue

        title   = entry.get("title", "").strip()
        raw_sum = entry.get("summary", "")
        desc    = BeautifulSoup(raw_sum, "html.parser").get_text() if HAS_REQUESTS else raw_sum
        desc    = desc.strip()
        source  = entry.get("source", {}).get("title", "Media Online")
        link    = entry.get("link", "")
        uid     = hashlib.md5(link.encode()).hexdigest()[:12]

        if not title:
            continue

        articles.append(_make_article(uid, source, title, desc, date_str, dt_str, link))
        if len(articles) >= max_items:
            break

    print(f"    Ditemukan: {len(articles)} artikel")
    return articles

# ── Scraping langsung situs berita ────────────────────────────────────────────

def scrape_direct(source_cfg: dict, keywords: list, max_items: int = 30,
                  date_from: str | None = None,
                  date_to: str | None = None) -> list:
    if not HAS_REQUESTS:
        return []

    query = "+".join(keywords)
    url   = source_cfg["search"].format(query=query)
    name  = source_cfg["name"]

    print(f"  {name}: '{query}'")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [!] {name} error: {e}")
        return []

    articles = []
    for item in soup.select(source_cfg["item"])[:max_items * 2]:
        title_el = item.select_one(source_cfg["title"])
        desc_el  = item.select_one(source_cfg["desc"])
        date_el  = item.select_one(source_cfg["date"])

        if not title_el:
            continue

        title    = title_el.get_text(strip=True)
        desc     = desc_el.get_text(strip=True) if desc_el else ""
        raw_date = date_el.get_text(strip=True) if date_el else ""
        date_str, dt_str = _parse_date(raw_date)
        link     = title_el.get("href", "")
        uid      = hashlib.md5((name + title).encode()).hexdigest()[:12]

        if not _in_range(date_str, date_from, date_to):
            continue

        articles.append(_make_article(uid, name, title, desc, date_str, dt_str, link))
        if len(articles) >= max_items:
            break

    print(f"    Ditemukan: {len(articles)} artikel")
    return articles

# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_media_online(keywords: list, max_items: int = 100,
                        date_from: str | None = None,
                        date_to: str | None = None) -> list:
    """Gabungkan Google News RSS + sumber langsung, deduplikasi by ID."""
    print(f"\n[Media Online] Kata kunci: {', '.join(keywords)}")

    articles: list = []

    # 1. Google News RSS — paling lengkap & reliable
    gn = scrape_google_news(keywords, max_items, date_from, date_to)
    articles.extend(gn)

    # 2. Scraping langsung jika masih kurang dari target
    remaining = max_items - len(articles)
    if remaining > 10:
        per_site = remaining // len(DIRECT_SOURCES)
        for cfg in DIRECT_SOURCES:
            direct = scrape_direct(cfg, keywords, per_site, date_from, date_to)
            articles.extend(direct)

    # Deduplikasi
    seen: set = set()
    unique: list = []
    for a in articles:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)

    print(f"[OK] Media Online total: {len(unique)} artikel\n")
    return unique[:max_items]
