#!/usr/bin/env python3
"""Konversi dataset Kaggle twitter-dataset-ppkm ke format SIAP Analytics JSON."""
import zipfile, io, csv, json, re, sys
from datetime import datetime, timedelta
from collections import Counter

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STOPWORDS = {
    "yang","dan","di","ke","dari","ini","itu","ada","dengan","untuk","pada",
    "atau","akan","sudah","juga","bisa","tidak","saya","kita","mereka","anda",
    "kamu","dia","nya","pun","lah","kah","ya","jadi","lebih","masih","belum",
    "sama","tapi","karena","kalau","maka","oleh","agar","demi","lagi","hanya",
    "bagi","saat","baru","waktu","orang","hal","cara","hari","semua","banyak",
    "sangat","jangan","harus","buat","lain","kali","pihak","setelah","sebelum",
    "dalam","sebuah","antara","gak","nggak","nih","sih","dong","aja","kok",
    "lho","wah","dgn","utk","krn","sdh","yg","jg","tp","klo","via","rt","amp",
}

POS_W = {"mendukung","setuju","bagus","baik","positif","berhasil","senang",
          "aman","lancar","efektif","tepat","benar","mendukung","membantu"}
NEG_W = {"menolak","kecewa","buruk","gagal","mahal","salah","rusak","masalah",
          "keluhan","protes","kritik","tidak bisa","tidak jelas","merugikan"}

LABEL_MAP = {"1": "pos", "2": "neu", "0": "neg"}


def clean(text):
    text = re.sub(r"http\S+|www\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#(\w+)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def main():
    zip_path = "ppkm_dataset.zip"
    out_path = "kaggle_ppkm.json"

    print("Membaca dataset Kaggle PPKM...")
    with zipfile.ZipFile(zip_path) as z:
        with z.open("INA_TweetsPPKM_Labeled_Pure.csv") as f:
            content = f.read().decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    rows = [r for r in reader if r.get("Tweet", "").strip()]
    print(f"Total tweet: {len(rows):,}")

    # Parse tanggal & sentimen
    parsed = []
    for r in rows:
        s = LABEL_MAP.get(r.get("sentiment", "").strip(), "neu")
        try:
            dt = datetime.fromisoformat(r["Date"].strip().replace("+00:00", ""))
        except Exception:
            dt = None
        parsed.append({"row": r, "s": s, "dt": dt})

    total = len(parsed)
    valid_dates = [p["dt"] for p in parsed if p["dt"]]
    date_from = min(valid_dates).strftime("%Y-%m-%d")
    date_to   = max(valid_dates).strftime("%Y-%m-%d")
    print(f"Periode  : {date_from} s/d {date_to}")

    counts  = Counter(p["s"] for p in parsed)
    pos_pct = round(counts["pos"] / total * 100)
    neg_pct = round(counts["neg"] / total * 100)
    neu_pct = 100 - pos_pct - neg_pct
    print(f"Positif  : {pos_pct}%  |  Negatif: {neg_pct}%  |  Netral: {neu_pct}%")

    # Trend 30 hari (dari tanggal awal dataset)
    from_dt = datetime.strptime(date_from, "%Y-%m-%d")
    buckets = {}
    for p in parsed:
        if p["dt"] is None:
            continue
        d = p["dt"].strftime("%Y-%m-%d")
        if d not in buckets:
            buckets[d] = {"pos": 0, "neg": 0, "neu": 0, "total": 0}
        buckets[d][p["s"]] += 1
        buckets[d]["total"] += 1

    trend = []
    for i in range(30):
        d  = (from_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        b  = buckets.get(d, {})
        bt = max(b.get("total", 0), 1)
        trend.append({
            "pos": round(b.get("pos", 0) / bt * 100) if b.get("total") else pos_pct,
            "neg": round(b.get("neg", 0) / bt * 100) if b.get("total") else neg_pct,
            "neu": round(b.get("neu", 0) / bt * 100) if b.get("total") else neu_pct,
        })

    # Mentions: 5 per sentimen, urutkan panjang tweet (proxy engagement)
    sorted_p = sorted(parsed, key=lambda p: len(p["row"].get("Tweet", "")), reverse=True)
    mentions = []
    used = Counter()
    for p in sorted_p:
        s   = p["s"]
        txt = clean(p["row"].get("Tweet", ""))
        if used[s] >= 5 or len(txt) < 20:
            continue
        if len(txt) > 200:
            txt = txt[:197] + "..."
        mentions.append({
            "txt":  txt,
            "pl":   "Twitter / X",
            "user": "@" + p["row"].get("User", "unknown").strip(),
            "s":    s,
            "cf":   85,
        })
        used[s] += 1
        if len(mentions) >= 15:
            break

    # Word cloud dari sampel 5000 tweet
    word_freq = Counter()
    for p in parsed[:5000]:
        words = re.findall(r"\b[a-zA-Z]{4,}\b", clean(p["row"].get("Tweet", "")).lower())
        word_freq.update(w for w in words if w not in STOPWORDS)

    kw = "PPKM"
    wc_words = [{"w": kw, "s": "kw", "weight": 5}]
    for word, count in word_freq.most_common(50):
        if word.lower() == kw.lower():
            continue
        s = "pos" if word in POS_W else "neg" if word in NEG_W else "neu"
        wc_words.append({"w": word, "s": s, "weight": min(5, max(1, count // 200))})
        if len(wc_words) >= 28:
            break

    # Rekomendasi
    recs = []
    if neg_pct > 30:
        recs.append({"level": "high", "title": "Resistensi Kebijakan PPKM Signifikan",
            "text": (f"Sentimen negatif {neg_pct}% menunjukkan resistensi kuat masyarakat. "
                     "Diperlukan pendekatan komunikasi lebih empatik dan penjelasan transparan "
                     "terkait urgensi kebijakan PPKM.")})
    else:
        recs.append({"level": "low", "title": "Penerimaan Kebijakan Cukup Baik",
            "text": (f"Mayoritas sentimen positif ({pos_pct}%) menunjukkan dukungan publik terhadap PPKM. "
                     "Pertahankan komunikasi proaktif untuk menjaga kepercayaan masyarakat.")})
    recs.append({"level": "medium", "title": "Monitoring Percakapan Media Sosial",
        "text": (f"Volume diskusi sangat tinggi ({total:,} tweet). Disarankan pemantauan "
                 "real-time setiap 6 jam untuk mendeteksi perubahan sentimen secara dini.")})
    recs.append({"level": "low", "title": "FGD Kelompok Sentimen Negatif",
        "text": ("Lakukan FGD dengan kelompok demografis yang paling banyak mengekspresikan "
                 "sentimen negatif untuk memahami kekhawatiran spesifik terkait implementasi PPKM.")})

    result = {
        "keywords":       ["PPKM"],
        "sources":        ["twitter"],
        "pos":            pos_pct,
        "neg":            neg_pct,
        "neu":            neu_pct,
        "total":          total,
        "trend":          trend,
        "srcData": [{
            "src":   "twitter",
            "label": "Twitter / X",
            "icon":  "X",
            "count": total,
            "pos":   pos_pct,
            "neg":   neg_pct,
            "neu":   neu_pct,
        }],
        "mentions":       mentions,
        "wcWords":        wc_words,
        "recs":           recs,
        "dateFrom":       date_from,
        "dateTo":         date_to,
        "_rawTweets":     total,
        "_generatedAt":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "_modelSentimen": "Human-Labeled (Kaggle: anggapurnama/twitter-dataset-ppkm)",
        "_source":        "Kaggle Dataset — INA_TweetsPPKM_Labeled_Pure.csv",
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    import os
    size = os.path.getsize(out_path)
    print()
    print("=" * 50)
    print(f"Output   : {out_path}  ({size:,} bytes)")
    print(f"Total    : {total:,} tweet")
    print(f"Positif  : {pos_pct}%")
    print(f"Negatif  : {neg_pct}%")
    print(f"Netral   : {neu_pct}%")
    print(f"Periode  : {date_from} s/d {date_to}")
    print("=" * 50)
    print()
    print("Siap diimport ke sentimen_app.html via tombol 'Impor Data JSON'")


if __name__ == "__main__":
    main()
