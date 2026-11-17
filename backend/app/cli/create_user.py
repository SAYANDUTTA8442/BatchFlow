import argparse
import getpass

from app.db.session import SessionLocal
from app.services.auth import create_user


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a BatchFlow user.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--roles", required=True, help="Comma-separated seeded role codes")
    args = parser.parse_args()
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        parser.error("Password must contain at least 12 characters")
    if password != confirmation:
        parser.error("Passwords do not match")
    with SessionLocal() as db:
        user = create_user(
            db, full_name=args.name, email=args.email, password=password,
            role_codes=[r.strip().lower() for r in args.roles.split(",") if r.strip()],
        )
        print(f"Created user {user.email} (id={user.id})")


if __name__ == "__main__":
    main()
