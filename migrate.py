#!/usr/bin/env python3
"""
Migrate Withings weight/body composition data to Garmin Connect.

Usage:
    python migrate.py [--dry-run] [--email EMAIL] [--password PASSWORD] [--csv PATH]

Credentials can also be supplied via environment variables:
    GARMIN_EMAIL, GARMIN_PASSWORD

If your account has MFA enabled, the code is prompted interactively on
first login (or read from GARMIN_MFA_CODE if set). Subsequent runs reuse
the tokens cached in ~/.garth and don't require re-login.
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
except ImportError:
    print("Missing dependency. Run:  pip install garminconnect")
    sys.exit(1)


TOKEN_STORE = Path.home() / ".garminconnect"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Withings weight/body composition data to Garmin Connect"
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("GARMIN_EMAIL"),
        help="Garmin Connect email address (or set GARMIN_EMAIL env var)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("GARMIN_PASSWORD"),
        help="Garmin Connect password (or set GARMIN_PASSWORD env var)",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default="weight.csv",
        help="Path to the Withings CSV export file (default: weight.csv)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Authenticate and parse the CSV but do NOT upload any data to Garmin",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Seconds to wait between uploads to avoid rate-limiting (default: 1.0)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def read_withings_csv(filepath: Path) -> list[dict]:
    """Parse a Withings body-composition CSV export.

    Returns a list of dicts with keys:
        timestamp       datetime  – local measurement time
        weight          float     – kg
        percent_fat     float|None
        percent_hydration float|None
        bone_mass       float|None – kg
        muscle_mass     float|None – kg
        has_composition bool      – True when body-comp fields are present
    """
    measurements: list[dict] = []

    with filepath.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_no, row in enumerate(reader, start=2):
            date_str = row["Date"].strip()
            weight_str = row["Poids (kg)"].strip()
            fat_str = row["Gras (kg)"].strip()
            bone_str = row["Masse osseuse (kg)"].strip()
            muscle_str = row["Masse musculaire (kg)"].strip()
            hydration_str = row["Hydratation (kg)"].strip()

            if not weight_str:
                print(f"  [SKIP] line {line_no} ({date_str}): missing weight value")
                continue

            try:
                weight_kg = float(weight_str)
                has_composition = bool(fat_str and bone_str and muscle_str and hydration_str)
                percent_fat = round(float(fat_str) / weight_kg * 100, 2) if fat_str else None
                percent_hydration = (
                    round(float(hydration_str) / weight_kg * 100, 2) if hydration_str else None
                )
                bone_mass_kg = float(bone_str) if bone_str else None
                muscle_mass_kg = float(muscle_str) if muscle_str else None
            except ValueError as exc:
                print(f"  [SKIP] line {line_no} ({date_str}): invalid numeric value – {exc}")
                continue

            measurements.append(
                {
                    "timestamp": datetime.fromisoformat(date_str),
                    "weight": weight_kg,
                    "percent_fat": percent_fat,
                    "percent_hydration": percent_hydration,
                    "bone_mass": bone_mass_kg,
                    "muscle_mass": muscle_mass_kg,
                    "has_composition": has_composition,
                }
            )

    return measurements


# ---------------------------------------------------------------------------
# Garmin authentication
# ---------------------------------------------------------------------------

def prompt_mfa() -> str:
    """Return the MFA code, from GARMIN_MFA_CODE if set, otherwise ask interactively."""
    code = os.environ.get("GARMIN_MFA_CODE")
    if code:
        return code
    return input("Garmin MFA - enter the 6-digit code you received: ")

def get_garmin_client(email: str, password: str) -> Garmin:
    """Authenticate against Garmin Connect, reusing cached tokens when possible."""
    client = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)

    token_dir = str(TOKEN_STORE)
    if TOKEN_STORE.exists():
        try:
            client.login(tokenstore=token_dir)
            print("Authenticated using cached tokens.")
            return client
        except GarminConnectTooManyRequestsError:
            # Re-raise immediately – retrying would make rate-limiting worse.
            raise
        except Exception:
            print("Cached tokens invalid or expired – re-authenticating…")

    # Persist tokens so the next run can resume without re-authenticating.
    client.login(tokenstore=token_dir)
    print("Authenticated and tokens saved.")
    return client


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------

def upload_measurement(client: Garmin, m: dict) -> None:
    """Upload one measurement to Garmin Connect.

    Rows that include full body composition use add_body_composition (FIT upload).
    Weight-only rows use the lighter add_weigh_in endpoint.
    """
    ts = m["timestamp"].isoformat()

    if m["has_composition"]:
        client.add_body_composition(
            timestamp=ts,
            weight=m["weight"],
            percent_fat=m["percent_fat"],
            percent_hydration=m["percent_hydration"],
            bone_mass=m["bone_mass"],
            muscle_mass=m["muscle_mass"],
        )
    else:
        client.add_weigh_in(weight=m["weight"], unitKey="kg", timestamp=ts)


def format_summary(m: dict) -> str:
    fat = f"{m['percent_fat']:.1f}%" if m["percent_fat"] is not None else "—"
    hyd = f"{m['percent_hydration']:.1f}%" if m["percent_hydration"] is not None else "—"
    bone = f"{m['bone_mass']} kg" if m["bone_mass"] is not None else "—"
    muscle = f"{m['muscle_mass']} kg" if m["muscle_mass"] is not None else "—"
    return (
        f"{m['timestamp']}  weight={m['weight']} kg  "
        f"fat={fat}  hydration={hyd}  bone={bone}  muscle={muscle}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    if not args.email or not args.password:
        print(
            "Error: Garmin credentials are required.\n"
            "  Use --email / --password flags, or set the\n"
            "  GARMIN_EMAIL / GARMIN_PASSWORD environment variables."
        )
        sys.exit(1)

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    # ---- Parse CSV ----
    print(f"Reading measurements from '{csv_path}'…")
    measurements = read_withings_csv(csv_path)
    full = sum(1 for m in measurements if m["has_composition"])
    weight_only = len(measurements) - full
    print(
        f"Parsed {len(measurements)} measurements "
        f"({full} with full body composition, {weight_only} weight-only)."
    )

    if not measurements:
        print("Nothing to upload.")
        return

    # ---- Authenticate ----
    print("\nAuthenticating with Garmin Connect…")
    try:
        client = get_garmin_client(args.email, args.password)
    except GarminConnectAuthenticationError as exc:
        print(f"Authentication failed: {exc}")
        sys.exit(1)
    except GarminConnectTooManyRequestsError as exc:
        print(f"Rate-limited by Garmin: {exc}")
        sys.exit(1)

    # ---- Dry-run mode ----
    if args.dry_run:
        print("\n--- DRY RUN MODE: no data will be uploaded ---")
        preview = measurements[:5]
        print(f"Would upload {len(measurements)} measurements. First {len(preview)}:")
        for m in preview:
            kind = "composition" if m["has_composition"] else "weight-only"
            print(f"  [{kind}] {format_summary(m)}")
        print("\nDry run complete. Connection to Garmin Connect is working.")
        return

    # ---- Upload ----
    print(f"\nUploading {len(measurements)} measurements…")
    success = 0
    errors = 0

    for m in measurements:
        try:
            upload_measurement(client, m)
            kind = "C" if m["has_composition"] else "W"
            print(f"  [OK/{kind}] {m['timestamp']}  {m['weight']} kg")
            success += 1
        except GarminConnectTooManyRequestsError as exc:
            print(f"  [RATE-LIMIT] {m['timestamp']} – {exc}")
            print("Stopping to avoid further rate-limiting. Re-run to continue.")
            errors += 1
            break
        except Exception as exc:
            print(f"  [ERROR] {m['timestamp']} – {exc}")
            errors += 1

        time.sleep(args.delay)

    print(f"\nDone.  Uploaded: {success}  Errors: {errors}")


if __name__ == "__main__":
    main()
