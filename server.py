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
import secrets

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, request, jsonify, send_file, redirect, url_for
from flask_login import (
    LoginManager, login_required, login_user, logout_user, current_user,
)
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from auth import init_db, get_user_by_id, verify_user, create_user, delete_user, get_all_users, update_password
from twitter_scraper import (
    scrape_tweets,
    analyze_sentiment_batch,
    compute_siap_output,
    HAS_TWSCRAPE,
    HAS_TRANSFORMERS,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SIAP_SECRET", secrets.token_hex(32))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Flask-Login ───────────────────────────────────────────────────────────────

login_manager = LoginManager(app)
login_manager.login_view = "login_page"


@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(user_id)


# In-memory job store  { job_id: {...} }
_jobs: dict = {}


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/login")
def login_page():
    if current_user.is_authenticated:
        return redirect("/")
    return send_file(os.path.join(BASE_DIR, "login.html"))


@app.route("/auth/login", methods=["POST"])
def auth_login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    remember = bool(request.form.get("remember"))

    if not username or not password:
        return redirect("/login?error=required")

    user = verify_user(username, password)
    if not user:
        return redirect("/login?error=invalid")

    login_user(user, remember=remember)
    return redirect(request.args.get("next") or "/")


@app.route("/auth/logout")
@login_required
def auth_logout():
    logout_user()
    return redirect("/login")


# ── Admin: manajemen pengguna ─────────────────────────────────────────────────

@app.route("/admin")
@login_required
def admin_page():
    if not current_user.is_admin():
        return redirect("/")
    return send_file(os.path.join(BASE_DIR, "admin.html"))


@app.route("/auth/users", methods=["GET"])
@login_required
def list_users():
    if not current_user.is_admin():
        return jsonify({"error": "Akses ditolak"}), 403
    return jsonify(get_all_users())


@app.route("/auth/users", methods=["POST"])
@login_required
def add_user():
    if not current_user.is_admin():
        return jsonify({"error": "Akses ditolak"}), 403
    body = request.get_json(force=True)
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    role     = body.get("role", "viewer")
    if not username or not password:
        return jsonify({"error": "Username dan password wajib diisi"}), 400
    if role not in ("admin", "viewer"):
        return jsonify({"error": "Role tidak valid"}), 400
    try:
        create_user(username, password, role)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409


@app.route("/auth/users/<int:uid>", methods=["DELETE"])
@login_required
def remove_user(uid):
    if not current_user.is_admin():
        return jsonify({"error": "Akses ditolak"}), 403
    if str(uid) == current_user.id:
        return jsonify({"error": "Tidak dapat menghapus akun sendiri"}), 400
    delete_user(uid)
    return jsonify({"ok": True})


@app.route("/auth/users/<int:uid>/password", methods=["PUT"])
@login_required
def change_password(uid):
    if not current_user.is_admin():
        return jsonify({"error": "Akses ditolak"}), 403
    body = request.get_json(force=True)
    pw = (body.get("password") or "").strip()
    if len(pw) < 6:
        return jsonify({"error": "Password minimal 6 karakter"}), 400
    update_password(uid, pw)
    return jsonify({"ok": True})


# ── Halaman utama ─────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return send_file(os.path.join(BASE_DIR, "sentimen_app.html"))


# ── API: info pengguna saat ini ───────────────────────────────────────────────

@app.route("/api/me")
@login_required
def api_me():
    return jsonify({
        "id":       current_user.id,
        "username": current_user.username,
        "role":     current_user.role,
    })


# ── API: mulai analisis ───────────────────────────────────────────────────────

@app.route("/api/analyze", methods=["POST"])
@login_required
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
@login_required
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
@login_required
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
@login_required
def api_info():
    return jsonify({
        "twscrape": HAS_TWSCRAPE,
        "indobert": HAS_TRANSFORMERS,
        "server":   "SIAP Analytics v2.3",
    })


# ── Background job runner ─────────────────────────────────────────────────────

def _set(job_id, **kw):
    if job_id in _jobs:
        _jobs[job_id].update(kw)


SCRAPE_TIMEOUT = 90

SRC_NAMES = {
    "twitter":      "Twitter / X",
    "media_online": "Media Online",
    "instagram":    "Instagram",
}


def _run_twitter(keywords, volume, date_from, date_to):
    if not HAS_TWSCRAPE:
        return []
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from twscrape import API
        api = API()
        return loop.run_until_complete(
            asyncio.wait_for(
                scrape_tweets(api, keywords, volume, "id", date_from, date_to),
                timeout=SCRAPE_TIMEOUT,
            )
        )
    except (asyncio.TimeoutError, Exception) as e:
        print(f"[!] Twitter: {type(e).__name__}: {e}")
        return []
    finally:
        loop.close()


def _run_media(keywords, volume, date_from, date_to):
    try:
        from scraper_media import scrape_media_online
        return scrape_media_online(keywords, volume, date_from, date_to)
    except Exception as e:
        print(f"[!] Media Online: {e}")
        return []


def _run_instagram(keywords, volume, date_from, date_to):
    try:
        from scraper_instagram import scrape_instagram_sync
        return scrape_instagram_sync(keywords, volume, date_from, date_to)
    except Exception as e:
        print(f"[!] Instagram: {e}")
        return []


def _heartbeat(job_id, stop_event, from_pct, to_pct, duration_sec):
    steps    = 20
    interval = duration_sec / steps
    delta    = (to_pct - from_pct) / steps
    for i in range(steps):
        if stop_event.is_set():
            break
        threading.Event().wait(interval)
        if job_id in _jobs and _jobs[job_id]["status"] == "running":
            new_pct = min(to_pct, round(from_pct + delta * (i + 1)))
            _jobs[job_id]["progress"] = new_pct


def _run_job(job_id, keywords, sources, date_from, date_to, volume, do_sent):
    try:
        all_tweets: list = []
        src_count  = max(len(sources), 1)
        per_source = max(30, volume // src_count)

        src_list = ", ".join(SRC_NAMES.get(s, s) for s in sources)
        _set(job_id, step=0, progress=10,
             message=f"Mengumpulkan data: {src_list}...")

        stop_hb = threading.Event()
        hb = threading.Thread(
            target=_heartbeat,
            args=(job_id, stop_hb, 10, 33, SCRAPE_TIMEOUT * src_count),
            daemon=True,
        )
        hb.start()

        RUNNERS = {
            "twitter":      (_run_twitter,   [keywords, per_source, date_from, date_to]),
            "media_online": (_run_media,      [keywords, per_source, date_from, date_to]),
            "instagram":    (_run_instagram,  [keywords, per_source, date_from, date_to]),
        }

        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {
                src: ex.submit(fn, *args)
                for src, (fn, args) in RUNNERS.items()
                if src in sources
            }

            for src, fut in futures.items():
                label = SRC_NAMES.get(src, src)
                try:
                    data = fut.result(timeout=SCRAPE_TIMEOUT + 20)
                    all_tweets.extend(data)
                    _set(job_id, message=f"{label}: {len(data)} data terkumpul")
                    print(f"[+] {label}: {len(data)} item")
                except FutureTimeout:
                    _set(job_id, message=f"{label}: timeout — lanjut")
                    print(f"[!] {label}: timeout")
                except Exception as e:
                    print(f"[!] {label}: {e}")

        stop_hb.set()

        _set(job_id, step=1, progress=38, message="Preprocessing & normalisasi teks")
        _set(job_id, step=2, progress=58, message="Tokenisasi dengan IndoBERT Tokenizer")

        if do_sent and all_tweets:
            _set(job_id, step=3, progress=72,
                 message=f"Klasifikasi sentimen {len(all_tweets)} data...")
            all_tweets = analyze_sentiment_batch(all_tweets)
        else:
            for t in all_tweets:
                t.setdefault("sentiment", "neu")
                t.setdefault("confidence", 50)

        _set(job_id, step=4, progress=90, message="Menyusun laporan & rekomendasi")
        result = compute_siap_output(all_tweets, keywords, date_from or "", date_to or "")

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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("=" * 52)
    print("  SIAP Analytics - Server")
    print("  Buka browser : http://localhost:5000")
    print("  Stop         : Ctrl+C")
    print("=" * 52)
    print(f"  twscrape  : {'OK' if HAS_TWSCRAPE else 'TIDAK TERINSTALL'}")
    print(f"  IndoBERT  : {'OK' if HAS_TRANSFORMERS else 'TIDAK TERINSTALL'}")
    print("=" * 52)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
