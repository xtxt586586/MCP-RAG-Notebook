"""Reset a user's password from the server shell.

This deliberately is a CLI-only recovery path.  There is no unauthenticated
HTTP password reset endpoint, so an operator must already have shell access to
the deployment host.
"""

import argparse
import asyncio
import getpass

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset the password for an existing user.",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email address of the existing account.",
    )
    return parser.parse_args()


async def reset_password(email: str, password: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == email),
        )
        user = result.scalar_one_or_none()
        if user is None:
            return False

        user.password_hash = hash_password(password)
        await session.commit()
        return True


def main() -> None:
    args = parse_args()
    email = args.email.strip().lower()
    password = getpass.getpass("New password (min 8 chars, letters and numbers): ")
    confirmation = getpass.getpass("Confirm new password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")
    if not any(char.isalpha() for char in password):
        raise SystemExit("Password must contain at least one letter.")
    if not any(char.isdigit() for char in password):
        raise SystemExit("Password must contain at least one digit.")

    updated = asyncio.run(reset_password(email, password))
    if not updated:
        raise SystemExit(f"No account found for {email}.")

    print(f"Password reset successfully for {email}.")


if __name__ == "__main__":
    main()
