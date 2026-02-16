# FB Marketplace Auto Post

Automates Facebook Marketplace vehicle draft creation with Playwright, including:
- field filling (`Jenis kendaraan`, `Tahun`, `Merek`, `Model`, `Harga`, `Jarak Tempuh`, `Keterangan`, `Lokasi`)
- photo upload
- `Simpan draf` and leave-page handling
- multi-listing run from `data.json`

## Requirements

- Python 3.9+
- Playwright

## Setup

```bash
pip install playwright
playwright install chromium
```

## Files

- `fb_marketplace_vehicle_dom_update.py`: main script
- `data.json`: listing input data (single or multiple posts)
- `cookies.json`: your FB cookies/session export (ignored by `.gitignore`)

## Run

```bash
python fb_marketplace_vehicle_dom_update.py
```

Optional flags:

```bash
python fb_marketplace_vehicle_dom_update.py --data-file data.json --cookies-file cookies.json --photo-path sample.png
```

## data.json format (multi-post)

```json
{
  "listings": [
    {
      "target_url": "https://www.facebook.com/marketplace/create/vehicle",
      "selling_url": "https://www.facebook.com/marketplace/you/selling",
      "photo_path": "sample.png",
      "vehicle_type": "Mobil/Truk",
      "year": "2025",
      "make": "Toyota",
      "model": "Avanza",
      "price": "200000",
      "mileage": "120000",
      "description": "nego tipis km rendah",
      "location": "Bekasi"
    }
  ]
}
```

Notes:
- If a `photo_path` is missing or invalid, the script falls back to the first image found in project root.
- If `data.json` is missing/empty, the script falls back to one default listing run.
