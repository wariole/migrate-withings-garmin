# migrate-withings-garmin

Migrate your weight and body composition history from **Withings** to **Garmin Connect**.

Useful if you switched to a Garmin scale (e.g. Index S2) and want your historical data available in Garmin Connect.

## What it does

- Reads the CSV export from the Withings Health Mate app
- Uploads each measurement to Garmin Connect via the official API
- Rows with full body composition (fat %, hydration %, bone mass, muscle mass) are uploaded as a FIT body-composition file
- Weight-only rows (no composition data) are uploaded as a simple weigh-in
- Caches authentication tokens locally so re-runs don't require logging in again
- Supports a `--dry-run` mode to verify the connection and data parsing before touching anything

## Prerequisites

- Python 3.10+
- A Withings CSV export (see [How to export](#how-to-export-from-withings))
- A Garmin Connect account

## Installation

```bash
git clone https://github.com/romain-ccc/migrate-withings-garmin.git
cd migrate-withings-garmin
pip install -r requirements.txt
```

## How to export from Withings

1. Open the **Health Mate** app (mobile or web at [healthmate.withings.com](https://healthmate.withings.com))
2. Go to **Profile → Settings → Export data** (or use the web: *My account → Download my data*)
3. Download the archive and locate **weight.csv**
4. Place it in the same folder as `migrate.py`, or pass its path with `--csv`

A sample `weight.csv` is included in this repository so you can verify the expected format before using your real export.

## Usage

### 1. Dry run (recommended first step)

Authenticates with Garmin Connect, parses the CSV, and prints a preview — **no data is uploaded**.

```bash
python migrate.py --email you@example.com --password yourpassword --dry-run
```

### 2. Full migration

```bash
python migrate.py --email you@example.com --password yourpassword
```

### 3. Using environment variables (avoids credentials in shell history)

```bash
export GARMIN_EMAIL=you@example.com
export GARMIN_PASSWORD=yourpassword
python migrate.py --dry-run
python migrate.py
```

### All options

| Flag | Default | Description |
|---|---|---|
| `--email` | `$GARMIN_EMAIL` | Garmin Connect email |
| `--password` | `$GARMIN_PASSWORD` | Garmin Connect password |
| `--csv PATH` | `weight.csv` | Path to the Withings CSV file |
| `--dry-run` | off | Parse + authenticate without uploading |
| `--delay SECONDS` | `1.0` | Pause between uploads to avoid rate-limiting |

## Notes

- **Authentication tokens** are cached in `~/.garth` after the first login. Subsequent runs reuse them automatically.
- **Rate limiting**: Garmin's API limits request frequency. The default 1-second delay between uploads works reliably for ~200+ records. Reduce with `--delay 0.5` at your own risk. If you hit a rate limit mid-run, just re-run the script.
- **Duplicates**: Garmin uses the measurement timestamp as a key. Running the script twice for the same data is safe — Garmin will silently ignore or overwrite duplicate timestamps.
- **MFA**: If your Garmin account has two-factor authentication enabled, the library will prompt you interactively on first login.

## Dependencies

| Package | Purpose |
|---|---|
| [garminconnect](https://github.com/cyberjunky/python-garminconnect) | Garmin Connect API wrapper |

## License

MIT — see [LICENSE](LICENSE).
