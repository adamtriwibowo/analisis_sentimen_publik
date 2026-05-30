# SIAP Analytics — Sistem Analisis Sentimen Publik

Aplikasi analisis sentimen berbasis web untuk memantau opini publik dari Twitter/X menggunakan model **IndoBERT** bahasa Indonesia. Dibangun dengan Python (Flask + twscrape) dan antarmuka HTML single-page.

## Fitur Utama

- **Scraping Twitter/X** tanpa API berbayar menggunakan [twscrape](https://github.com/vladkens/twscrape)
- **Analisis Sentimen IndoBERT** — model `mdhugol/indonesia-bert-sentiment-classification` (fine-tuned untuk Bahasa Indonesia)
- **Dashboard interaktif** — tren 30 hari, distribusi sentimen, word cloud, sampel sebutan
- **Ekspor PDF** laporan lengkap siap cetak
- **Fallback simulasi** otomatis jika scraping tidak tersedia
- **Dark / Light mode**

## Arsitektur

```
Browser (sentimen_app.html)
        │  keyword input
        ▼
Flask Server (server.py)          ← python server.py
        │
        ├── twitter_scraper.py    ← twscrape (scraping Twitter)
        │
        └── IndoBERT              ← transformers (analisis sentimen)
                │
                ▼
        JSON hasil → Browser menampilkan dashboard
```

## Instalasi

```bash
pip install -r requirements.txt
```

**Dependensi utama:**

| Library | Fungsi |
|---|---|
| `flask` | Web server backend |
| `twscrape` | Scraper Twitter/X |
| `transformers` + `torch` | Model IndoBERT sentiment |

## Cara Penggunaan

### 1. Daftarkan akun Twitter (hanya sekali)

Ambil cookies `auth_token` dan `ct0` dari browser setelah login ke x.com:
- Buka DevTools (F12) → Application → Cookies → https://x.com

```bash
python twitter_scraper.py --add-cookies USERNAME AUTH_TOKEN CT0
```

### 2. Jalankan server

```bash
python server.py
```

Buka browser: **http://localhost:5000**

### 3. Gunakan aplikasi

1. Ketik kata kunci (contoh: `BPJS Kesehatan`, `program MBG`)
2. Pilih rentang tanggal
3. Klik **Mulai Analisis Sentimen**
4. Hasil tampil otomatis dengan sentimen nyata dari Twitter

### Alternatif: CLI (tanpa server)

```bash
# Scraping + analisis sentimen ke file JSON
python twitter_scraper.py -k "BPJS Kesehatan" -m 500 --from 2025-01-01 --to 2025-12-31

# Import hasilnya di sentimen_app.html via tombol "Impor Data JSON"
```

## Parameter CLI

```
python twitter_scraper.py [opsi]

  -k, --keywords KW [KW ...]   Kata kunci pencarian (wajib)
  -m, --max N                  Jumlah maksimal tweet (default: 500)
  --from YYYY-MM-DD            Tanggal mulai
  --to   YYYY-MM-DD            Tanggal akhir
  --lang LANG                  Kode bahasa (default: id)
  -o, --output FILE            File output JSON (default: output_twitter.json)
  --no-sentiment               Lewati analisis IndoBERT (lebih cepat)
  --add-cookies USER TOKEN CT0 Login via cookies browser
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

Model di-cache otomatis setelah download pertama (~400MB). Tidak perlu download ulang.

## Struktur File

```
final/
├── sentimen_app.html      # UI dashboard (single-page app)
├── server.py              # Flask backend + job runner
├── twitter_scraper.py     # Scraper Twitter + IndoBERT pipeline
├── requirements.txt       # Dependensi Python
└── .gitignore
```

## Catatan Keamanan

- File `accounts.db` (kredensial Twitter) **tidak di-commit** ke Git
- Output JSON scraping **tidak di-commit** ke Git
- Gunakan akun Twitter alternatif/sekunder untuk scraping

## Lisensi

Proyek ini dibuat untuk keperluan akademis — Program Studi S2, Adam Tri Wibowo.
