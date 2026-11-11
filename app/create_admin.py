"""Create an administrator locally: python -m app.create_admin LOGIN."""

import argparse
import asyncio
import warnings
from getpass import GetPassWarning, getpass

from pydantic import ValidationError

from app.core.config import get_settings
from app.db.session import create_database
from app.schemas.auth import Credentials
from app.services.auth import AuthService, LoginAlreadyExistsError


async def create_admin(credentials: Credentials) -> None:
    settings = get_settings()
    database = create_database(settings)
    try:
        async with database.session_factory() as session:
            await AuthService(session, settings).register(
                credentials.login, credentials.password.get_secret_value()
            )
    finally:
        await database.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an administrator account")
    parser.add_argument("login")
    args = parser.parse_args()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Password: ")
    except GetPassWarning:
        parser.exit(1, "A terminal is required to enter the password securely.\n")
    try:
        credentials = Credentials(login=args.login, password=password)
    except ValidationError:
        parser.exit(2, "Invalid login or password; check the existing credential requirements.\n")
    try:
        asyncio.run(create_admin(credentials))
    except LoginAlreadyExistsError:
        parser.exit(1, "Login already taken.\n")
    print("Administrator created.")


if __name__ == "__main__":
    main()
