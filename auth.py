"""
Fyers OAuth login flow.

Fyers access tokens expire daily (they invalidate at a fixed time each day,
not on a rolling basis), so this needs to run once per trading day before
anything else. This script:

  1. Builds the login URL and asks you to open it, log in, and paste back
     the redirected URL (it contains an auth_code).
  2. Exchanges the auth_code for an access_token.
  3. Caches the access_token to disk so other modules can reuse it without
     re-authenticating.

Run this interactively each morning:
    python auth.py
"""

import os
import re
from fyers_apiv3 import fyersModel

import config


def generate_login_url() -> str:
    session = fyersModel.SessionModel(
        client_id=config.FYERS_CLIENT_ID,
        secret_key=config.FYERS_SECRET_KEY,
        redirect_uri=config.FYERS_REDIRECT_URI,
        response_type=config.RESPONSE_TYPE,
        grant_type=config.GRANT_TYPE,
    )
    return session.generate_authcode()


def extract_auth_code(redirected_url: str) -> str:
    """Pull the auth_code query param out of the URL the user pastes back."""
    match = re.search(r"auth_code=([^&]+)", redirected_url)
    if not match:
        raise ValueError(
            "Couldn't find auth_code in that URL. Make sure you pasted the "
            "full URL you were redirected to after logging in."
        )
    return match.group(1)


def exchange_for_token(auth_code: str) -> str:
    session = fyersModel.SessionModel(
        client_id=config.FYERS_CLIENT_ID,
        secret_key=config.FYERS_SECRET_KEY,
        redirect_uri=config.FYERS_REDIRECT_URI,
        response_type=config.RESPONSE_TYPE,
        grant_type=config.GRANT_TYPE,
    )
    session.set_token(auth_code)
    response = session.generate_token()

    try:
        return response["access_token"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"Token exchange failed. Raw response: {response}") from e


def save_token(token: str) -> None:
    os.makedirs(os.path.dirname(config.TOKEN_STORE_PATH), exist_ok=True)
    with open(config.TOKEN_STORE_PATH, "w") as f:
        f.write(token.strip())


def load_cached_token() -> str | None:
    if os.path.exists(config.TOKEN_STORE_PATH):
        with open(config.TOKEN_STORE_PATH, "r") as f:
            token = f.read().strip()
            return token or None
    return None


def run_interactive_login() -> str:
    """Full flow: prints login URL, waits for pasted redirect, saves token."""
    if not config.FYERS_CLIENT_ID or not config.FYERS_SECRET_KEY:
        raise EnvironmentError(
            "FYERS_CLIENT_ID / FYERS_SECRET_KEY not set. Export them or put "
            "them in your environment before running this."
        )

    url = generate_login_url()
    print("\n1. Open this URL, log in, and approve the app:\n")
    print(url)
    print("\n2. After approving, you'll be redirected to your redirect_uri")
    print("   with an auth_code in the query string. Paste that FULL URL below.\n")

    redirected_url = input("Paste redirected URL: ").strip()
    auth_code = extract_auth_code(redirected_url)
    token = exchange_for_token(auth_code)
    save_token(token)
    print("\nAccess token saved. Good for today's trading session.")
    return token


if __name__ == "__main__":
    run_interactive_login()
