"""Add the two section demo accounts to an already initialized workspace."""
import getpass
import hashlib
import secrets

from django.core.management.base import BaseCommand, CommandError
from tracking import json_store


class Command(BaseCommand):
    help = "Add digital2 and digital3 without changing existing accounts or passwords."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for newly added local demo users; prompts when omitted.")

    def handle(self, *args, **options):
        users = json_store.read("users")
        new_ids = [username for username in ("digital2", "digital3") if not any(u["username"] == username or u["id"] == username for u in users)]
        if not new_ids:
            self.stdout.write("Demo users already exist. Nothing changed.")
            return
        password = options["password"] or getpass.getpass("New demo user password: ")
        if not password:
            raise CommandError("Password must not be empty.")
        for username in new_ids:
            salt = secrets.token_hex(16)
            users.append({
                "id": username, "username": username, "name": f"디지털 사용자 {username[-1]}",
                "role": "USER", "team_id": "SECTION_DIGITAL_COMMUNICATION",
                "password_salt": salt,
                "password_hash": hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 390000).hex(),
            })
        json_store.write("users", users)
        self.stdout.write("Added: " + ", ".join(new_ids))
