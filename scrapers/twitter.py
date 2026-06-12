#!/usr/bin/env python3
"""
Twitter Scraper untuk SIAP Analytics
Menggunakan twscrape (https://github.com/vladkens/twscrape) + IndoBERT

CARA LOGIN (pilih salah satu):

  A. Via cookies browser (DIREKOMENDASIKAN - bypass Cloudflare):
     1. Login ke x.com di Chrome/Firefox
     2. Buka DevTools (F12) -> Application -> Cookies -> https://x.com
     3. Salin nilai cookie: auth_token  dan  ct0
     4. Jalankan (dari root project):
        python scrapers/twitter.py --add-cookies USERNAME AUTH_TOKEN CT0

  B. Via username/password (bisa gagal karena Cloudflare):
     python scrapers/twitter.py --add-account USERNAME PASSWORD EMAIL EMAIL_PASS

SCRAPING:
  python scrapers/twitter.py -k "BPJS Kesehatan" -m 500
  python scrapers/twitter.py -k "program MBG" "makan bergizi" -m 1000 --from 2025-05-01 --to 2025-05-30
"""

import asyncio
import json
import re
import sys
import os
import argparse
from datetime import datetime, timedelta
from collections import Counter

# Fix encoding Windows terminal
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Dependency check ──────────────────────────────────────────────────────────

try:
    from twscrape import API
    HAS_TWSCRAPE = True
except ImportError:
    HAS_TWSCRAPE = False

try:
    from transformers import pipeline as hf_pipeline
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

# ── Konstanta ─────────────────────────────────────────────────────────────────

SENTIMENT_MODEL = "mdhugol/indonesia-bert-sentiment-classification"
LABEL_MAP = {"LABEL_0": "pos", "LABEL_1": "neu", "LABEL_2": "neg"}

STOPWORDS_ID = {
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "ada", "dengan",
    "untuk", "pada", "atau", "akan", "sudah", "juga", "bisa", "tidak",
    "saya", "kita", "mereka", "anda", "kamu", "dia", "nya", "pun", "lah",
    "kah", "ya", "no", "jadi", "lebih", "masih", "belum", "sama", "seperti",
    "tapi", "karena", "kalau", "maka", "oleh", "agar", "demi", "lagi",
    "hanya", "punya", "soal", "bagi", "saat", "rt", "via", "re", "yg",
    "dgn", "utk", "krn", "sdh", "jg", "tp", "klo", "gak", "nggak",
    "nih", "sih", "dong", "deh", "aja", "kok", "lho", "wah",
    "jangan", "harus", "buat", "baru", "waktu", "tahun", "orang", "hal",
    "cara", "hari", "lain", "kali", "pihak", "paling", "sekitar", "setelah",
    "sebelum", "antara", "dalam", "sebuah", "semua", "banyak", "sangat",
}

POS_WORDS = {
    "bagus", "baik", "positif", "senang", "berhasil", "mantap", "sukses",
    "maju", "harapan", "puas", "hebat", "keren", "apresiasi", "mendukung",
    "setuju", "benar", "tepat", "efektif", "bermanfaat", "membantu",
    "inovatif", "transparan", "memuaskan",
}

NEG_WORDS = {
    "kecewa", "buruk", "gagal", "jelek", "lambat", "mahal", "salah",
    "rusak", "masalah", "keluhan", "kritik", "protes", "menolak", "tolak",
    "mengecewakan", "merugikan", "membebani", "tidak adil",
    "korupsi", "curang", "bohong",
}

# ── Text cleaner ──────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    text = re.sub(r"http\S+|www\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#(\w+)", r"\1", text)
    text = re.sub(r"[^\w\s.,!?']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ── Scraper ───────────────────────────────────────────────────────────────────

async def scrape_tweets(
    api,
    keywords: list,
    max_tweets: int = 500,
    lang: str = "id",
    date_from: str = None,
    date_to: str = None,
) -> list:
    parts = [f'"{kw}"' for kw in keywords]
    query = " OR ".join(parts) + f" lang:{lang}"
    if date_from:
        query += f" since:{date_from}"
    if date_to:
        # Twitter until: eksklusif, tambah 1 hari agar tanggal akhir ikut terscrape
        until_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        query += f" until:{until_dt.strftime('%Y-%m-%d')}"

    print(f"\nQuery: {query}")
    print(f"Target: {max_tweets} tweet\n")

    def make_tweet_dict(tweet):
        raw = tweet.rawContent
        return {
            "id":         str(tweet.id),
            "user":       f"@{tweet.user.username}",
            "name":       tweet.user.displayname,
            "text":       raw,
            "text_clean": clean_text(raw),
            "date":       tweet.date.strftime("%Y-%m-%d"),
            "datetime":   tweet.date.strftime("%Y-%m-%d %H:%M:%S"),
            "likes":      tweet.likeCount,
            "retweets":   tweet.retweetCount,
            "replies":    tweet.replyCount,
            "views":      tweet.viewCount or 0,
            "source":     "twitter",
            "sentiment":  None,
            "confidence": 0,
        }

    tweets = []
    async for tweet in api.search(query, limit=max_tweets):
        tweets.append(make_tweet_dict(tweet))
        if len(tweets) % 50 == 0:
            print(f"  Terkumpul (search): {len(tweets)} tweet...")

    # Fallback ke user_tweets jika search kosong atau hanya tweet lama (sebelum 2020)
    needs_fallback = (
        not tweets or
        all(t["date"] < "2020-01-01" for t in tweets)
    )
    if needs_fallback:
        if not tweets:
            print(f"\n[!] Search tidak menemukan tweet dalam rentang tanggal ini.")
        else:
            print(f"\n[!] Search hanya menemukan tweet lama (sebelum 2020).")
        print("    Beralih ke mode user_tweets (scrape timeline akun relevan)...")
        tweets = await scrape_user_timelines(api, keywords, max_tweets, date_from, date_to)

    return tweets


AKUN_RELEVAN = {
    # Pemerintah & lembaga
    "BPJSKesehatanRI", "KemenkesRI", "KemensosRI", "kemendag", "KemenkeuRI",
    "KemenPUPR", "BPK_RI", "KPK_RI", "Sekretariat_KSP", "BNPB_Indonesia",
    "DPR_RI", "setnasri", "kemenpanrb",
    # Media nasional
    "detikcom", "kompascom", "tempodotco", "CNNIndonesia", "BBCIndonesia",
    "tribunnews", "antaranews", "liputan6dotcom", "metrotvnews", "tvonenews",
    # Tokoh publik (sample)
    "jokowi", "sandiuno", "mohmahfudmd",
}

async def scrape_user_timelines(api, keywords: list, max_tweets: int, date_from: str, date_to: str) -> list:
    """Scrape timeline akun-akun relevan, filter by keyword & tanggal."""
    kw_lower = [k.lower() for k in keywords]
    collected = []
    target_per_account = max(10, max_tweets // len(AKUN_RELEVAN))

    for username in list(AKUN_RELEVAN):
        if len(collected) >= max_tweets:
            break
        try:
            user = await api.user_by_login(username)
            if not user:
                continue
            async for tweet in api.user_tweets(user.id, limit=target_per_account * 3):
                raw = tweet.rawContent.lower()
                tweet_date = tweet.date.strftime("%Y-%m-%d")
                if date_from and tweet_date < date_from:
                    break  # tweet sudah lebih lama dari filter
                if date_to and tweet_date > date_to:
                    continue
                if any(kw in raw for kw in kw_lower):
                    collected.append({
                        "id":         str(tweet.id),
                        "user":       f"@{tweet.user.username}",
                        "name":       tweet.user.displayname,
                        "text":       tweet.rawContent,
                        "text_clean": clean_text(tweet.rawContent),
                        "date":       tweet_date,
                        "datetime":   tweet.date.strftime("%Y-%m-%d %H:%M:%S"),
                        "likes":      tweet.likeCount,
                        "retweets":   tweet.retweetCount,
                        "replies":    tweet.replyCount,
                        "views":      tweet.viewCount or 0,
                        "source":     "twitter",
                        "sentiment":  None,
                        "confidence": 0,
                    })
                    if len(collected) % 20 == 0:
                        print(f"  Terkumpul (user_tweets): {len(collected)} tweet...")
        except Exception as e:
            pass  # skip akun yang error

    return collected

# ── Sentiment analysis ────────────────────────────────────────────────────────

def analyze_sentiment_batch(tweets: list) -> list:
    if not HAS_TRANSFORMERS:
        print("\n[!] transformers tidak terinstall - sentiment dilewati.")
        print("    Install: pip install transformers torch")
        for t in tweets:
            t["sentiment"] = "neu"
            t["confidence"] = 50
        return tweets

    print(f"\nMemuat model IndoBERT ({SENTIMENT_MODEL}) ...")
    classifier = hf_pipeline(
        "sentiment-analysis",
        model=SENTIMENT_MODEL,
        tokenizer=SENTIMENT_MODEL,
        device=-1,
    )

    batch_size = 32
    total = len(tweets)
    print(f"Menganalisis {total} tweet (batch {batch_size}) ...")

    for i in range(0, total, batch_size):
        batch = tweets[i : i + batch_size]
        texts = [t["text_clean"] or t["text"] for t in batch]
        try:
            results = classifier(texts, truncation=True, max_length=512)
            for j, res in enumerate(results):
                batch[j]["sentiment"] = LABEL_MAP.get(res["label"], "neu")
                batch[j]["confidence"] = round(res["score"] * 100)
        except Exception as exc:
            print(f"  [!] Batch {i//batch_size+1} error: {exc} - diisi netral")
            for t in batch:
                t["sentiment"] = "neu"
                t["confidence"] = 50

        done = min(i + batch_size, total)
        print(f"  Progress: {done}/{total} ({done*100//total}%)")

    return tweets

# ── Statistics + SIAP-compatible output ──────────────────────────────────────

def compute_siap_output(tweets: list, keywords: list, date_from: str, date_to: str) -> dict:
    total = len(tweets)
    if total == 0:
        return {}

    counts = Counter(t.get("sentiment", "neu") for t in tweets)
    pos_pct = round(counts.get("pos", 0) / total * 100)
    neg_pct = round(counts.get("neg", 0) / total * 100)
    neu_pct = 100 - pos_pct - neg_pct

    # Trend 30 hari
    from_dt = datetime.strptime(date_from, "%Y-%m-%d")
    buckets = {}
    for t in tweets:
        d = t["date"]
        if d not in buckets:
            buckets[d] = {"pos": 0, "neg": 0, "neu": 0, "total": 0}
        s = t.get("sentiment") or "neu"
        buckets[d][s] += 1
        buckets[d]["total"] += 1

    trend = []
    for i in range(30):
        d = (from_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        b = buckets.get(d, {})
        bt = max(b.get("total", 0), 1)
        if b.get("total", 0) > 0:
            trend.append({
                "pos": round(b["pos"] / bt * 100),
                "neg": round(b["neg"] / bt * 100),
                "neu": round(b["neu"] / bt * 100),
            })
        else:
            trend.append({"pos": pos_pct, "neg": neg_pct, "neu": neu_pct})

    # ── Source breakdown (multi-source) ───────────────────────────────────────
    SRC_META = {
        "twitter":     ("Twitter / X",  "X"),
        "media_online": ("Media Online", "Media"),
        "instagram":   ("Instagram",     "IG"),
    }
    sources_present = sorted(set(t.get("source", "twitter") for t in tweets))
    src_data = []
    for src in sources_present:
        src_tweets = [t for t in tweets if t.get("source") == src]
        if not src_tweets:
            continue
        sc  = Counter(t.get("sentiment", "neu") for t in src_tweets)
        st  = max(len(src_tweets), 1)
        lbl, icon = SRC_META.get(src, (src, src))
        src_data.append({
            "src":   src,
            "label": lbl,
            "icon":  icon,
            "count": len(src_tweets),
            "pos":   round(sc.get("pos", 0) / st * 100),
            "neg":   round(sc.get("neg", 0) / st * 100),
            "neu":   round(sc.get("neu", 0) / st * 100),
        })

    # ── Mentions sample (campur semua sumber) ──────────────────────────────────
    SRC_LABEL = {
        "twitter":     "Twitter / X",
        "media_online": "Media Online",
        "instagram":   "Instagram",
    }
    sorted_tw = sorted(tweets, key=lambda t: t["likes"] + t["retweets"] * 3, reverse=True)
    mentions = []
    used_sentiments = Counter()
    for t in sorted_tw:
        s = t.get("sentiment") or "neu"
        if used_sentiments[s] < 5:
            text_display = t["text_clean"] or t["text"]
            if len(text_display) > 200:
                text_display = text_display[:197] + "..."
            mentions.append({
                "txt":  text_display,
                "pl":   SRC_LABEL.get(t.get("source", "twitter"), "Media"),
                "user": t["user"],
                "s":    s,
                "cf":   t.get("confidence", 80),
            })
            used_sentiments[s] += 1
        if len(mentions) >= 15:
            break

    # Word cloud
    word_freq = Counter()
    for t in tweets:
        words = re.findall(r"\b[a-zA-Z]{4,}\b", (t["text_clean"] or "").lower())
        word_freq.update(w for w in words if w not in STOPWORDS_ID)

    kw_lower = {w.lower() for kw in keywords for w in kw.split()}
    wc_words = [{"w": kw, "s": "kw", "weight": 5} for kw in keywords]
    for word, count in word_freq.most_common(40):
        if word in kw_lower or word in STOPWORDS_ID:
            continue
        s = "pos" if word in POS_WORDS else "neg" if word in NEG_WORDS else "neu"
        weight = min(5, max(1, round(count / max(total // 25, 1))))
        wc_words.append({"w": word, "s": s, "weight": weight})
        if len(wc_words) >= 28:
            break

    kw_str = ", ".join(f'"{k}"' for k in keywords)
    recs = []
    if neg_pct > 45:
        recs.append({"level": "high", "title": "Respons Segera Diperlukan",
            "text": f"Sentimen negatif dominan ({neg_pct}%) terhadap {kw_str} di Twitter/X mengindikasikan krisis persepsi publik. Pimpinan disarankan mengeluarkan pernyataan resmi atau tindakan konkret dalam 48 jam ke depan."})
    elif neg_pct > 30:
        recs.append({"level": "medium", "title": "Perhatian & Tindak Lanjut",
            "text": f"Sentimen negatif ({neg_pct}%) cukup signifikan. Disarankan segera merespons kekhawatiran utama terkait {kw_str} dan memperkuat komunikasi proaktif."})
    else:
        recs.append({"level": "low", "title": "Kondisi Persepsi Terkendali",
            "text": f"Sentimen publik terhadap {kw_str} berada pada kondisi positif ({pos_pct}% positif, {neg_pct}% negatif). Pertahankan program komunikasi."})

    if total > 5000:
        recs.append({"level": "medium", "title": "Monitoring Intensif",
            "text": f"Volume diskusi tinggi ({total:,} tweet). Disarankan meningkatkan frekuensi pemantauan setiap 6 jam dan menyiapkan tim respons cepat."})

    recs.append({"level": "low", "title": "Strategi Komunikasi Digital Twitter",
        "text": "Aktivitas tinggi di Twitter/X memerlukan strategi komunikasi digital terencana. Rekomendasikan tim humas aktif merespons sebutan kunci dan berkolaborasi dengan KOL."})

    recs.append({"level": "low", "title": "Analisis Lanjutan & Evaluasi",
        "text": "Lakukan pemantauan berkala setiap 7 hari. Identifikasi kluster opini negatif dan jadwalkan FGD di wilayah dengan konsentrasi keluhan tertinggi."})

    return {
        "keywords":          keywords,
        "sources":           ["twitter"],
        "pos":               pos_pct,
        "neg":               neg_pct,
        "neu":               neu_pct,
        "total":             total,
        "trend":             trend,
        "srcData":           src_data,
        "mentions":          mentions,
        "wcWords":           wc_words,
        "recs":              recs,
        "dateFrom":          date_from,
        "dateTo":            date_to,
        "_rawTweets":        total,
        "_generatedAt":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "_modelSentimen":    SENTIMENT_MODEL if HAS_TRANSFORMERS else "lexicon-fallback",
    }

# ── CLI ───────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Twitter Scraper untuk SIAP Analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  # Login via cookies (DIREKOMENDASIKAN):
  python twitter_scraper.py --add-cookies myuser AUTH_TOKEN_VALUE CT0_VALUE

  # Login via password (bisa diblokir Cloudflare):
  python twitter_scraper.py --add-account myuser mypass email@gmail.com emailpass

  # Scraping:
  python twitter_scraper.py -k "BPJS Kesehatan" -m 500
  python twitter_scraper.py -k "program MBG" -m 1000 --from 2025-05-01 --to 2025-05-30
        """,
    )
    parser.add_argument("-k", "--keywords", nargs="+", metavar="KW",
                        help="Kata kunci pencarian")
    parser.add_argument("-m", "--max", type=int, default=500, metavar="N",
                        help="Maks tweet (default: 500)")
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD",
                        help="Tanggal mulai (default: 30 hari lalu)")
    parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD",
                        help="Tanggal akhir (default: hari ini)")
    parser.add_argument("--lang", default="id",
                        help="Kode bahasa (default: id)")
    parser.add_argument("-o", "--output", default="output_twitter.json",
                        help="File output (default: output_twitter.json)")
    parser.add_argument("--no-sentiment", action="store_true",
                        help="Lewati analisis sentimen IndoBERT")
    parser.add_argument("--add-account", nargs=4,
                        metavar=("USERNAME", "PASSWORD", "EMAIL", "EMAIL_PASS"),
                        help="Login via username/password")
    parser.add_argument("--add-cookies", nargs=3,
                        metavar=("USERNAME", "AUTH_TOKEN", "CT0"),
                        help="Login via cookies browser (lebih reliable)")
    parser.add_argument("--list-accounts", action="store_true",
                        help="Tampilkan akun yang terdaftar")

    args = parser.parse_args()

    if not HAS_TWSCRAPE:
        print("ERROR: twscrape tidak terinstall. Jalankan: pip install twscrape")
        sys.exit(1)

    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _accounts_db  = os.path.join(_project_root, "instance", "accounts.db")
    api = API(_accounts_db)

    # ── Tampilkan daftar akun ─────────────────────────────────────────────
    if args.list_accounts:
        accounts = await api.pool.get_all()
        if accounts:
            print(f"Akun terdaftar ({len(accounts)}):")
            for a in accounts:
                print(f"  @{a.username}  aktif={a.active}")
        else:
            print("Belum ada akun yang terdaftar.")
        return

    # ── Login via cookies (DIREKOMENDASIKAN) ─────────────────────────────
    if args.add_cookies:
        username, auth_token, ct0 = args.add_cookies
        print(f"Mendaftarkan @{username} via cookies ...")
        cookies = {"auth_token": auth_token, "ct0": ct0}
        await api.pool.add_account(
            username=username,
            password="cookies_auth",
            email="cookies@auth.local",
            email_password="cookies_auth",
            cookies=cookies,
        )
        accounts = await api.pool.get_all()
        active = [a for a in accounts if a.username == username]
        if active:
            print(f"[OK] Akun @{username} berhasil didaftarkan via cookies.")
        else:
            print(f"[OK] Akun @{username} ditambahkan. Siap digunakan.")
        return

    # ── Login via username/password ───────────────────────────────────────
    if args.add_account:
        username, password, email, email_pass = args.add_account
        print(f"Mendaftarkan @{username} via password ...")
        print("[INFO] Jika gagal karena Cloudflare, gunakan --add-cookies sebagai gantinya.")
        await api.pool.add_account(username, password, email, email_pass)
        await api.pool.login_all()
        print(f"[OK] Akun @{username} berhasil didaftarkan.")
        return

    # ── Wajib: keywords ───────────────────────────────────────────────────
    if not args.keywords:
        parser.print_help()
        sys.exit(1)

    accounts = await api.pool.get_all()
    if not accounts:
        print("ERROR: Belum ada akun Twitter.")
        print("Jalankan dulu (pilih salah satu):")
        print("  python twitter_scraper.py --add-cookies USERNAME AUTH_TOKEN CT0")
        print("  python twitter_scraper.py --add-account USERNAME PASSWORD EMAIL EMAIL_PASS")
        sys.exit(1)

    today = datetime.now()
    date_from = args.date_from or (today - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to   = args.date_to   or today.strftime("%Y-%m-%d")

    print("=" * 60)
    print("SIAP Analytics - Twitter Scraper")
    print("=" * 60)
    print(f"Kata kunci : {', '.join(args.keywords)}")
    print(f"Periode    : {date_from} s/d {date_to}")
    print(f"Maks tweet : {args.max:,}")
    print(f"Bahasa     : {args.lang}")
    print(f"Output     : {args.output}")
    print("=" * 60)

    tweets = await scrape_tweets(api, args.keywords, args.max, args.lang, date_from, date_to)

    if not tweets:
        print("\n[!] Tidak ada tweet ditemukan. Coba perluas rentang tanggal atau ubah kata kunci.")
        sys.exit(0)

    print(f"\n[OK] Berhasil mengambil {len(tweets)} tweet.")

    if not args.no_sentiment:
        tweets = analyze_sentiment_batch(tweets)
    else:
        print("[INFO] --no-sentiment aktif, semua tweet ditandai netral.")
        for t in tweets:
            t["sentiment"] = "neu"
            t["confidence"] = 50

    result = compute_siap_output(tweets, args.keywords, date_from, date_to)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"[OK] Output disimpan: {args.output}")
    print(f"  Total   : {result['total']:,} tweet")
    print(f"  Positif : {result['pos']}%")
    print(f"  Negatif : {result['neg']}%")
    print(f"  Netral  : {result['neu']}%")
    print(f"{'='*60}")
    print("")
    print("Langkah berikutnya:")
    print("  1. Buka sentimen_app.html di browser")
    print("  2. Klik tombol 'Impor Data JSON'")
    print(f"  3. Pilih file: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
