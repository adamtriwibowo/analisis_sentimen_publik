#!/usr/bin/env python3
"""
Instagram Scraper untuk SIAP Analytics
Menggunakan instagrapi (https://github.com/adw0rd/instagrapi)

Setup (sekali):
  pip install instagrapi
  python scraper_instagram.py --add-account USERNAME PASSWORD

Scraping hashtag sesuai kata kunci.
"""
import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SESSION_FILE = Path(__file__).parent / "instagram_session.json"

try:
    from instagrapi import Client
    HAS_INSTAGRAPI = True
except ImportError:
    HAS_INSTAGRAPI = False

from twitter_scraper import clean_text

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client() -> "Client":
    cl = Client()
    cl.delay_range = [2, 5]
    if SESSION_FILE.exists():
        cl.load_settings(SESSION_FILE)
        # Re-login agar token fresh
        settings = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        username = settings.get("username", "")
        password = settings.get("password", "")
        if username and password:
            cl.login(username, password)
    return cl


def _kw_to_hashtags(keywords: list) -> list:
    """Konversi keyword ke format hashtag (hilangkan spasi & karakter khusus)."""
    tags = []
    for kw in keywords:
        tag = re.sub(r"[^a-zA-Z0-9]", "", kw.replace(" ", "").lower())
        if tag:
            tags.append(tag)
        # Versi dengan spasi dihilangkan saja
        tag2 = re.sub(r"\s+", "", kw.lower())
        tag2 = re.sub(r"[^a-zA-Z0-9]", "", tag2)
        if tag2 and tag2 != tag:
            tags.append(tag2)
    return list(dict.fromkeys(tags))  # deduplikasi, pertahankan urutan


def _media_to_dict(media, keyword_check: list) -> dict | None:
    caption = (media.caption_text or "").strip()
    if not caption:
        return None

    # Filter: hanya ambil jika caption relevan dengan keyword
    cap_lower = caption.lower()
    if not any(kw.lower() in cap_lower for kw in keyword_check):
        return None

    try:
        date_obj = media.taken_at
        date_str = date_obj.strftime("%Y-%m-%d")
        dt_str   = date_obj.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")
        dt_str   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "id":         str(media.pk),
        "user":       f"@{media.user.username}",
        "name":       getattr(media.user, "full_name", "") or media.user.username,
        "text":       caption,
        "text_clean": clean_text(caption),
        "date":       date_str,
        "datetime":   dt_str,
        "likes":      getattr(media, "like_count", 0) or 0,
        "retweets":   0,
        "replies":    getattr(media, "comment_count", 0) or 0,
        "views":      getattr(media, "view_count", 0) or 0,
        "source":     "instagram",
        "sentiment":  None,
        "confidence": 0,
    }

# ── Login ─────────────────────────────────────────────────────────────────────

def add_ig_account(username: str, password: str) -> bool:
    if not HAS_INSTAGRAPI:
        print("[!] instagrapi tidak terinstall. Install: pip install instagrapi")
        return False
    try:
        cl = Client()
        cl.delay_range = [2, 5]
        cl.login(username, password)
        settings = cl.get_settings()
        settings["username"] = username
        settings["password"] = password
        SESSION_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Akun Instagram @{username} berhasil login. Session disimpan.")
        return True
    except Exception as e:
        print(f"[!] Login Instagram gagal: {e}")
        return False

# ── Scraper ───────────────────────────────────────────────────────────────────

def scrape_instagram_sync(keywords: list, max_posts: int = 100,
                          date_from: str | None = None,
                          date_to: str | None = None) -> list:
    """Scrape Instagram hashtag posts berdasarkan keyword."""
    if not HAS_INSTAGRAPI:
        print("[!] instagrapi tidak terinstall. Install: pip install instagrapi")
        print("    Kemudian login: python scraper_instagram.py --add-account USER PASS")
        return []

    if not SESSION_FILE.exists():
        print("[!] Belum ada akun Instagram.")
        print("    Login dulu: python scraper_instagram.py --add-account USERNAME PASSWORD")
        return []

    try:
        cl = _get_client()
    except Exception as e:
        print(f"[!] Instagram login gagal: {e}")
        return []

    hashtags = _kw_to_hashtags(keywords)
    per_tag  = max(10, max_posts // max(len(hashtags), 1))
    posts    = []
    seen_ids: set = set()

    print(f"\n[Instagram] Hashtag: {', '.join('#'+t for t in hashtags)}")

    for tag in hashtags:
        if len(posts) >= max_posts:
            break
        print(f"  #{tag} (top + recent, maks {per_tag} per jenis)...")
        try:
            # Top posts
            for media in cl.hashtag_medias_top(tag, amount=per_tag):
                if str(media.pk) in seen_ids:
                    continue
                d = _media_to_dict(media, keywords)
                if d is None:
                    continue
                if date_from and d["date"] < date_from:
                    continue
                if date_to and d["date"] > date_to:
                    continue
                seen_ids.add(str(media.pk))
                posts.append(d)

            # Recent posts
            for media in cl.hashtag_medias_recent(tag, amount=per_tag):
                if len(posts) >= max_posts:
                    break
                if str(media.pk) in seen_ids:
                    continue
                d = _media_to_dict(media, keywords)
                if d is None:
                    continue
                if date_from and d["date"] < date_from:
                    continue
                if date_to and d["date"] > date_to:
                    continue
                seen_ids.add(str(media.pk))
                posts.append(d)

            print(f"    Terkumpul: {len(posts)} post sejauh ini")
        except Exception as e:
            print(f"  [!] Error #{tag}: {e}")

    print(f"[OK] Instagram total: {len(posts)} post\n")
    return posts[:max_posts]

# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram Scraper untuk SIAP Analytics")
    parser.add_argument("--add-account", nargs=2, metavar=("USERNAME", "PASSWORD"),
                        help="Login dan simpan session Instagram")
    parser.add_argument("-k", "--keywords", nargs="+", metavar="KW",
                        help="Kata kunci / hashtag yang dicari")
    parser.add_argument("-m", "--max", type=int, default=50)
    args = parser.parse_args()

    if args.add_account:
        add_ig_account(*args.add_account)
    elif args.keywords:
        results = scrape_instagram_sync(args.keywords, args.max)
        print(f"\nHasil: {len(results)} post")
        for r in results[:5]:
            print(f"  {r['user']} | {r['text'][:80]}")
    else:
        parser.print_help()
