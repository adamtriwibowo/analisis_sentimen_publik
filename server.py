#!/usr/bin/env python3
"""
SIAP Analytics — Flask Backend Server
Jalankan : python server.py
Buka     : http://localhost:5000
"""

import sys
import os
import uuid
import asyncio
import threading

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, request, jsonify, send_file

from twitter_scraper import (
    scrape_tweets,
    analyze_sentiment_batch,
    compute_siap_output,
    HAS_TWSCRAPE,
    HAS_TRANSFORMERS,
)

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# In-memory job store  { job_id: {...} }
_jobs: dict = {}


# ── Halaman utama ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "sentimen_app.html"))


# ── API: mulai analisis ───────────────────────────────────────────────────────

@app.route("/api/analyze", methods=["POST"])
def start_analyze():
    body      = request.get_json(force=True)
    keywords  = body.get("keywords", [])
    sources   = body.get("sources", ["twitter"])
    date_from = body.get("dateFrom") or None
    date_to   = body.get("dateTo")   or None
    volume    = int(body.get("volume", 500))
    do_sent   = bool(body.get("sentiment", True))

    if not keywords:
        return jsonify({"error": "keywords wajib diisi"}), 400

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status":   "running",
        "step":     0,
        "progress": 0,
        "message":  "Memulai...",
        "result":   None,
        "error":    None,
    }

    t = threading.Thread(
        target=_run_job,
        args=(job_id, keywords, sources, date_from, date_to, volume, do_sent),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


# ── API: cek status job ───────────────────────────────────────────────────────

@app.route("/api/status/<job_id>")
def job_status(job_id):
    j = _jobs.get(job_id)
    if not j:
        return jsonify({"error": "Job tidak ditemukan"}), 404
    return jsonify({
        "status":   j["status"],
        "step":     j["step"],
        "progress": j["progress"],
        "message":  j["message"],
        "error":    j.get("error"),
    })


# ── API: ambil hasil job ──────────────────────────────────────────────────────

@app.route("/api/result/<job_id>")
def job_result(job_id):
    j = _jobs.get(job_id)
    if not j:
        return jsonify({"error": "Job tidak ditemukan"}), 404
    if j["status"] == "error":
        return jsonify({"error": j["error"]}), 500
    if j["status"] != "done":
        return jsonify({"error": "Belum selesai"}), 202
    return jsonify(j["result"])


# ── API: info sistem ──────────────────────────────────────────────────────────

@app.route("/api/info")
def api_info():
    return jsonify({
        "twscrape":     HAS_TWSCRAPE,
        "indobert":     HAS_TRANSFORMERS,
        "server":       "SIAP Analytics v2.3",
    })


# ── Background job runner ─────────────────────────────────────────────────────

def _set(job_id, **kw):
    if job_id in _jobs:
        _jobs[job_id].update(kw)


def _run_job(job_id, keywords, sources, date_from, date_to, volume, do_sent):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Step 0 — Pengumpulan data
        _set(job_id, step=0, progress=10, message="Mengumpulkan data dari sumber terpilih")
        tweets = []

        if "twitter" in sources and HAS_TWSCRAPE:
            from twscrape import API
            api = API()
            tweets = loop.run_until_complete(
                scrape_tweets(api, keywords, volume, "id", date_from, date_to)
            )

        # Step 1 — Preprocessing
        _set(job_id, step=1, progress=35, message="Preprocessing & normalisasi teks")

        # Step 2 — Tokenisasi
        _set(job_id, step=2, progress=58, message="Tokenisasi dengan IndoBERT Tokenizer")

        # Step 3 — Klasifikasi sentimen
        if do_sent and tweets:
            _set(job_id, step=3, progress=72, message="Klasifikasi sentimen multi-kelas")
            tweets = analyze_sentiment_batch(tweets)
        else:
            for t in tweets:
                t.setdefault("sentiment", "neu")
                t.setdefault("confidence", 50)

        # Step 4 — Susun laporan
        _set(job_id, step=4, progress=90, message="Menyusun laporan & rekomendasi")
        result = compute_siap_output(tweets, keywords, date_from or "", date_to or "")

        if not result:
            result = {
                "keywords": keywords, "sources": sources,
                "total": 0, "pos": 0, "neg": 0, "neu": 0,
                "trend": [], "srcData": [], "mentions": [],
                "wcWords": [], "recs": [], "dateFrom": date_from or "",
                "dateTo": date_to or "", "_empty": True,
            }

        _set(job_id, status="done", step=5, progress=100, message="Selesai", result=result)

    except Exception as exc:
        _set(job_id, status="error", error=str(exc))
    finally:
        loop.close()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 52)
    print("  SIAP Analytics - Server")
    print("  Buka browser : http://localhost:5000")
    print("  Stop         : Ctrl+C")
    print("=" * 52)
    print(f"  twscrape  : {'OK' if HAS_TWSCRAPE else 'TIDAK TERINSTALL'}")
    print(f"  IndoBERT  : {'OK' if HAS_TRANSFORMERS else 'TIDAK TERINSTALL'}")
    print("=" * 52)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
