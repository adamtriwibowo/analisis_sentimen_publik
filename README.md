# SIAP Analytics — Sistem Analisis Sentimen Publik

Dashboard analisis sentimen publik berbasis web untuk memantau opini masyarakat dari Twitter/X, Media Online, dan Instagram menggunakan model **IndoBERT** bahasa Indonesia. Dibangun dengan Python (Flask) dan antarmuka HTML single-page.

## Fitur Utama

- **Multi-source scraping** — Twitter/X (twscrape), Media Online (feedparser + BeautifulSoup), Instagram (instagrapi)
- **Analisis Sentimen IndoBERT** — model `mdhugol/indonesia-bert-sentiment-classification` (akurasi 94.7%)
- **Dashboard interaktif** — tren 30 hari, distribusi sentimen, word cloud, sampel sebutan per platform
- **SIAP Bot** — chatbot asisten built-in untuk analisis hasil (platform, trend, rekomendasi, export)
- **Autentikasi Flask-Login** — halaman login, admin panel manajemen pengguna
- **Ekspor PDF & CSV** — laporan lengkap siap cetak
- **Dark / Light mode**, Aurora background, BorderGlow effects
- **Fallback simulasi** otomatis jika scraping tidak tersedia

## Struktur Proyek

```
siap-analytics/
├── server.py                  # Entry point — Flask app & job runner
├── auth.py                    # Autentikasi Flask-Login + SQLite user DB
├── requirements.txt
├── .gitignore
├── README.md
│
├── templates/                 # Halaman HTML
│   ├── index.html             # Dashboard utama (single-page app)
│   ├── login.html             # Halaman login
│   └── admin.html             # Panel manajemen pengguna
│
├── scrapers/                  # Modul pengumpulan data
│   ├── __init__.py
│   ├── twitter.py             # Scraper Twitter/X via twscrape
│   ├── media.py               # Scraper media online via feedparser + BS4
│   └── instagram.py           # Scraper Instagram via instagrapi
│
├── ml/                        # Machine learning / NLP (reserved)
│   └── __init__.py
│
├── scripts/                   # Utility & tools
│   └── convert_kaggle.py      # Konversi dataset Kaggle ke format SIAP
│
├── instance/                  # Runtime data — TIDAK di-commit (gitignored)
│   ├── accounts.db            # Kredensial akun twscrape
│   └── siap_users.db          # Database pengguna (password hash)
│
└── data/                      # Dataset — TIDAK di-commit (gitignored)
    ├── kaggle_ppkm.json
    └── ppkm_dataset.zip
```

## Arsitektur Sistem

```
Browser (templates/index.html)
        │  keyword + sumber + tanggal
        ▼
Flask Server (server.py)
        │
        ├── scrapers/twitter.py     ← twscrape (Twitter/X)
        ├── scrapers/media.py       ← feedparser + BS4 (Media Online)
        ├── scrapers/instagram.py   ← instagrapi (Instagram)
        │
        ├── IndoBERT                ← transformers (analisis sentimen)
        │        │
        │        ▼
        │   { pos, neg, neu, trend, mentions, wcWords, recs }
        │
        ├── auth.py                 ← Flask-Login + SQLite
        └── instance/               ← DB runtime (gitignored)
```

## Instalasi

```bash
pip install -r requirements.txt
```

**Dependensi utama:**

| Library | Fungsi |
|---|---|
| `flask` + `flask-login` | Web server + autentikasi |
| `twscrape` | Scraper Twitter/X tanpa API berbayar |
| `feedparser` + `beautifulsoup4` | Scraper media online |
| `transformers` + `torch` | Model IndoBERT sentiment |

## Cara Penggunaan

### 1. Jalankan server

```bash
python server.py
```

Buka browser: **http://localhost:5000**

Login default: `admin` / `siap2025`

### 2. Daftarkan akun Twitter (untuk scraping real)

Ambil cookies dari browser setelah login ke x.com:
- Buka DevTools (F12) → Application → Cookies → https://x.com
- Salin `auth_token` dan `ct0`

```bash
python scrapers/twitter.py --add-cookies USERNAME AUTH_TOKEN CT0
```

### 3. Gunakan aplikasi

1. Login → masuk dashboard
2. Ketik kata kunci (contoh: `BPJS Kesehatan`, `PPKM`)
3. Pilih sumber data dan rentang tanggal
4. Klik **Mulai Analisis Sentimen**
5. Tanya **SIAP Bot** (ikon chat kanan bawah) untuk analisis hasil

### 4. CLI — scraping manual tanpa server

```bash
# Scraping + analisis sentimen
python scrapers/twitter.py -k "BPJS Kesehatan" -m 500 --from 2026-01-01 --to 2026-06-01

# Import hasilnya di dashboard via tombol "Impor Data JSON"
```

## Parameter CLI Twitter Scraper

```
python scrapers/twitter.py [opsi]

  -k, --keywords KW [KW ...]   Kata kunci pencarian (wajib)
  -m, --max N                  Jumlah maksimal tweet (default: 500)
  --from YYYY-MM-DD            Tanggal mulai
  --to   YYYY-MM-DD            Tanggal akhir
  --lang LANG                  Kode bahasa (default: id)
  -o, --output FILE            File output JSON (default: output_twitter.json)
  --no-sentiment               Lewati analisis IndoBERT (lebih cepat)
  --add-cookies USER TOKEN CT0 Login via cookies browser (direkomendasikan)
  --add-account USER PASS EMAIL EMAILPASS  Login via password
  --list-accounts              Tampilkan akun terdaftar
```

## Model Sentimen

Model: [`mdhugol/indonesia-bert-sentiment-classification`](https://huggingface.co/mdhugol/indonesia-bert-sentiment-classification)

| Label | Kelas |
|---|---|
| LABEL_0 | Positif |
| LABEL_1 | Netral |
| LABEL_2 | Negatif |

Model di-cache otomatis setelah download pertama (~400 MB). Tidak perlu download ulang.

## Keamanan

- `instance/` (berisi `accounts.db` & `siap_users.db`) **tidak di-commit** ke Git
- `data/` (dataset mentah) **tidak di-commit** ke Git
- Gunakan akun Twitter alternatif/sekunder untuk scraping
- Ganti password default `siap2025` setelah instalasi via Admin Panel

## Lisensi

Proyek ini dibuat untuk keperluan akademis — Program Studi S2, Adam Tri Wibowo © 2026
