"""Initialize independent web runtime data; never overwrite existing collections."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent


def initialize(password):
    data = ROOT / "data"
    if not (data / "users.json").exists() and len(password) < 8:
        raise ValueError("Use a demo password of at least 8 characters.")
    data.mkdir(exist_ok=True)
    for source in (ROOT / "fixtures").glob("*.json"):
        target = data / source.name
        if not target.exists():
            target.write_bytes(source.read_bytes())
    for name in ("tracking_logs", "vehicle_requests"):
        target = data / f"{name}.json"
        if not target.exists():
            target.write_text("[]", encoding="utf-8")
    target = data / "users.json"
    if not target.exists():
        if len(password) < 8:
            raise ValueError("Use a demo password of at least 8 characters.")
        users = []
        for username, name, role, team in (
            ("admin", "관리자", "ADMIN", None),
            ("digital", "디지털통신기술섹션", "USER", "SECTION_DIGITAL_COMMUNICATION"),
            ("cold-dx", "냉간 DX 섹션", "USER", "SECTION_COLD_DX"),
            ("steelmaking", "제강연주섹션", "USER", "SECTION_STEELMAKING_CASTING"),
        ):
            salt = secrets.token_hex(16)
            users.append({"id": username, "username": username, "name": name,
                          "role": role, "team_id": team, "password_salt": salt,
                          "password_hash": hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 390000).hex()})
        target.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-password", action="store_true", help="Save a generated demo password inside ignored runtime data")
    args = parser.parse_args()
    password = os.environ.get("WEB_DEMO_PASSWORD")
    if not password:
        password = secrets.token_urlsafe(12) if args.generated_password else getpass.getpass("Demo account password (8+ characters): ")
    existing = (ROOT / "data/users.json").exists()
    initialize(password)
    print("Runtime data ready. Existing data is preserved.")
    if args.generated_password and not existing:
        password_file = ROOT / "data" / "demo-password.txt"
        password_file.write_text(password, encoding="utf-8")
        print(f"Generated local demo password saved to: {password_file}")
