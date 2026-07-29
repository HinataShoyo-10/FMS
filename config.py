"""
Central config. Never hardcode credentials here - load from environment
variables (or a local .env file that is gitignored).

Required env vars:
    FYERS_CLIENT_ID       e.g. "ABCD1234-100"  (your app_id from the Fyers dashboard)
    FYERS_SECRET_KEY      the app secret shown when you created the app
    FYERS_REDIRECT_URI    must exactly match what you registered for the app
    FYERS_PIN              (optional) your 4-digit trading PIN, only needed
                           if you automate the login step itself

Create the app at: https://myapi.fyers.in/dashboard
"""

import os

FYERS_CLIENT_ID = os.environ.get("FYERS_CLIENT_ID", "")
FYERS_SECRET_KEY = os.environ.get("FYERS_SECRET_KEY", "")
FYERS_REDIRECT_URI = os.environ.get("FYERS_REDIRECT_URI", "https://127.0.0.1")

# Where the access token gets cached locally (gitignore this file!)
TOKEN_STORE_PATH = os.path.join(os.path.dirname(__file__), "data", "access_token.txt")

# Response/grant type per Fyers OAuth spec - normally never need to change these
RESPONSE_TYPE = "code"
GRANT_TYPE = "authorization_code"

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs")
