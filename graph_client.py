"""
graph_client.py — Fetches emails and Teams messages from Microsoft Graph API.

HOW AUTHENTICATION WORKS:
  We use "device code flow" — when you first run a sync, it prints a URL and a code.
  You open that URL in your browser, enter the code, and log in with your work account.
  After that, the token is saved to 'token_cache.json' so you don't have to log in again.

REQUIRED SETUP (one-time):
  1. Go to https://portal.azure.com
  2. Azure Active Directory → App registrations → New registration
  3. Name: "Work Tracker", Supported account types: "Single tenant"
  4. After creation, note the "Application (client) ID" and "Directory (tenant) ID"
  5. Go to API permissions → Add a permission → Microsoft Graph → Delegated:
       - User.Read
       - Mail.Read
       - Chat.Read
       - offline_access
  6. Grant admin consent (or ask your IT admin to do this)
  7. Add these to your .env file:
       AZURE_CLIENT_ID=your-client-id-here
       AZURE_TENANT_ID=your-tenant-id-here
"""

import os
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

try:
    import msal
except ImportError:
    raise ImportError("Please run: pip install msal")

load_dotenv()

CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
TENANT_ID = os.getenv("AZURE_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE_FILE = "token_cache.json"

# Permissions we're requesting from Microsoft
SCOPES = ["User.Read", "Mail.Read", "Chat.Read"]


def _load_cache():
    """Load the saved token cache from disk (so we don't re-authenticate every time)."""
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
    return cache


def _save_cache(cache):
    """Save token cache to disk if it changed."""
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())


def _get_app(cache):
    """Create an MSAL PublicClientApplication (used for device code flow)."""
    if not CLIENT_ID or not TENANT_ID:
        raise ValueError(
            "Missing AZURE_CLIENT_ID or AZURE_TENANT_ID in your .env file.\n"
            "See graph_client.py for setup instructions."
        )
    return msal.PublicClientApplication(
        client_id=CLIENT_ID,
        authority=AUTHORITY,
        token_cache=cache
    )


def authenticate():
    """
    Get a valid access token. Uses cached token if available, otherwise
    triggers device code login (user visits a URL and enters a code).

    Returns the access token string, or None on failure.
    """
    cache = _load_cache()
    app = _get_app(cache)

    # Try to get a token silently from the cache first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]

    # No cached token — start device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print("Failed to start login flow:", flow.get("error_description"))
        return None

    # Print instructions for the user
    print("\n" + "="*60)
    print("MICROSOFT LOGIN REQUIRED")
    print("="*60)
    print(flow["message"])
    print("="*60 + "\n")

    # Wait for the user to complete the login in their browser
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        _save_cache(cache)
        print("Login successful!")
        return result["access_token"]
    else:
        print("Login failed:", result.get("error_description"))
        return None


def _headers(token):
    """Build the Authorization header for Graph API requests."""
    return {"Authorization": f"Bearer {token}"}


def fetch_emails(token, date_str):
    """
    Fetch emails received on a specific date from Outlook.

    Args:
        token: Access token from authenticate()
        date_str: 'YYYY-MM-DD' — only emails from this date will be returned

    Returns:
        List of dicts: {message_id, subject, sender, received_at, body_preview}
    """
    # Graph API filter: emails received on or after midnight of the target date
    date_start = f"{date_str}T00:00:00Z"
    date_end_parts = date_str.split("-")
    # We filter by date in Python after fetching, simpler than complex OData filter

    url = (
        f"{GRAPH_BASE}/me/messages"
        f"?$select=id,subject,from,receivedDateTime,bodyPreview"
        f"&$filter=receivedDateTime ge {date_start}"
        f"&$orderby=receivedDateTime asc"
        f"&$top=100"
    )

    results = []
    while url:
        response = requests.get(url, headers=_headers(token))
        if response.status_code != 200:
            print(f"Email fetch failed: {response.status_code} — {response.text[:200]}")
            break

        data = response.json()
        for msg in data.get("value", []):
            received = msg.get("receivedDateTime", "")
            # Only keep emails from the target date
            if not received.startswith(date_str):
                # Since results are sorted ascending, we can stop once we pass our date
                if received > f"{date_str}T23:59:59Z":
                    url = None
                    break
                continue

            sender_obj = msg.get("from", {}).get("emailAddress", {})
            sender = f"{sender_obj.get('name', '')} <{sender_obj.get('address', '')}>"

            results.append({
                "message_id": msg["id"],
                "subject": msg.get("subject", "(no subject)"),
                "sender": sender,
                "received_at": received.replace("Z", "").replace("T", " "),  # clean up for display
                "body_preview": msg.get("bodyPreview", "")[:300]
            })

        # Graph API returns a next-page link if there are more results
        url = data.get("@odata.nextLink")

    print(f"Fetched {len(results)} emails for {date_str}.")
    return results


def fetch_teams_messages(token, date_str):
    """
    Fetch Teams chat messages from all your chats for a specific date.

    Note: Fetching Teams messages requires the Chat.Read permission and
    may require admin consent in some organisations.

    Args:
        token: Access token from authenticate()
        date_str: 'YYYY-MM-DD'

    Returns:
        List of dicts: {message_id, chat_name, sender, content, sent_at}
    """
    results = []

    # Step 1: Get list of all chats the user is in
    chats_url = f"{GRAPH_BASE}/me/chats?$select=id,topic,chatType&$top=50"
    chats_response = requests.get(chats_url, headers=_headers(token))

    if chats_response.status_code != 200:
        print(f"Teams chat list failed: {chats_response.status_code} — {chats_response.text[:200]}")
        return results

    chats = chats_response.json().get("value", [])
    print(f"Found {len(chats)} Teams chats. Fetching messages...")

    for chat in chats:
        chat_id = chat["id"]
        # Use the chat topic as the name, or fall back to the chat type
        chat_name = chat.get("topic") or chat.get("chatType", "Chat")

        # Step 2: Get messages from this chat for the target date
        messages_url = (
            f"{GRAPH_BASE}/me/chats/{chat_id}/messages"
            f"?$top=50"
        )

        response = requests.get(messages_url, headers=_headers(token))
        if response.status_code != 200:
            # Some chats may not be accessible, skip silently
            continue

        for msg in response.json().get("value", []):
            created = msg.get("createdDateTime", "")
            if not created.startswith(date_str):
                continue

            # Extract sender name
            sender_obj = msg.get("from", {}) or {}
            user_obj = sender_obj.get("user", {}) or {}
            sender = user_obj.get("displayName", "Unknown")

            # Extract plain text content (Teams messages are HTML)
            body = msg.get("body", {})
            content = body.get("content", "")
            # Strip basic HTML tags for readability
            content = _strip_html(content)

            if not content.strip():
                continue  # Skip empty/system messages

            results.append({
                "message_id": msg["id"],
                "chat_name": chat_name,
                "sender": sender,
                "content": content[:500],  # Limit to 500 chars
                "sent_at": created.replace("Z", "").replace("T", " ")
            })

    print(f"Fetched {len(results)} Teams messages for {date_str}.")
    return results


def _strip_html(text):
    """Remove HTML tags from a string. Simple version for Teams message bodies."""
    import re
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", " ", text)
    # Collapse multiple spaces/newlines
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


if __name__ == "__main__":
    # Quick test: authenticate and fetch today's emails
    from datetime import date
    token = authenticate()
    if token:
        today = date.today().isoformat()
        emails = fetch_emails(token, today)
        print(f"\nFirst email: {emails[0] if emails else 'none'}")
