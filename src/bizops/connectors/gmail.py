"""Gmail connector for pulling invoice emails.

Based on the production pipeline built for Desi Delight Marketplace.
Handles OAuth2 auth, email search, attachment extraction, and deduplication.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Any

from bizops.utils.config import BizOpsConfig
from bizops.utils.display import print_info, print_warning

# Gmail API scopes — read-only for safety
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailConnector:
    """Connect to Gmail API and search for invoice emails."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self._service = None

    @property
    def service(self) -> Any:
        """Lazy-initialize the Gmail API service."""
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self) -> Any:
        """Authenticate with Gmail API using OAuth2 credentials.

        Expects credentials.json from Google Cloud Console.
        Token is cached at config.gmail_token_path for subsequent runs.

        When running headless (MCP server), browser-based OAuth is skipped —
        a pre-existing token with a valid refresh_token is required.
        """
        import os

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = None
        token_path = self.config.gmail_token_path
        headless = bool(os.environ.get("MCP_SERVER") or not os.isatty(0))

        # Load existing token
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        # Refresh or create new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    raise RuntimeError(
                        f"Gmail token refresh failed: {e}. "
                        "Run 'bizops config setup' interactively to re-authorize."
                    ) from e
            elif headless:
                raise RuntimeError(
                    "Gmail requires interactive OAuth login but running headless (MCP server). "
                    "Run 'bizops config setup' in a terminal first to authorize, "
                    "then restart the MCP server."
                )
            else:
                from google_auth_oauthlib.flow import InstalledAppFlow

                if not self.config.gmail_credentials_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {self.config.gmail_credentials_path}. "
                        "Download from Google Cloud Console and run: "
                        "bizops config setup --credentials /path/to/credentials.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.config.gmail_credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save refreshed/new token for next run
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def search_invoices(
        self,
        start_date: str,
        end_date: str,
        vendor_filter: str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search Gmail for invoice emails within a date range.

        Args:
            start_date: Start date as YYYY-MM-DD.
            end_date: End date as YYYY-MM-DD.
            vendor_filter: Optional vendor name to filter by.
            max_results: Max emails to return (default from config).

        Returns:
            List of email dicts with subject, sender, date, body, attachments.
        """
        max_results = max_results or self.config.gmail_max_results

        # Build Gmail search query
        query_parts = [
            f"after:{start_date}",
            f"before:{end_date}",
            "subject:(invoice OR bill OR statement OR receipt OR payment OR order)",
        ]

        # Add vendor email filter if specified
        if vendor_filter:
            matching_vendors = [
                v for v in self.config.vendors
                if vendor_filter.lower() in v.name.lower()
            ]
            if matching_vendors:
                email_patterns = []
                for v in matching_vendors:
                    email_patterns.extend(v.email_patterns)
                if email_patterns:
                    from_query = " OR ".join(f"from:{p}" for p in email_patterns)
                    query_parts.append(f"({from_query})")

        query = " ".join(query_parts)
        print_info(f"Gmail query: [dim]{query}[/dim]")

        # Execute search
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = results.get("messages", [])
        if not messages:
            return []

        # Fetch full message details
        emails = []
        for msg_ref in messages:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="full")
                .execute()
            )
            parsed = self._parse_message(msg)
            if parsed:
                emails.append(parsed)

        return emails

    def _parse_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a Gmail API message into a structured dict."""
        headers = {
            h["name"].lower(): h["value"]
            for h in message.get("payload", {}).get("headers", [])
        }

        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        date_str = headers.get("date", "")

        # Extract body text
        body = self._extract_body(message.get("payload", {}))

        # Extract attachments info
        attachments = self._extract_attachments(message)

        # Parse date
        parsed_date = self._parse_date(date_str)

        # Match to vendor
        vendor_name = self._match_vendor(sender)

        return {
            "message_id": message.get("id", ""),
            "subject": subject,
            "sender": sender,
            "date": parsed_date,
            "body": body,
            "attachments": attachments,
            "vendor": vendor_name,
            "raw_date": date_str,
        }

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract plain text body from message payload."""
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Check parts for multipart messages
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        return ""

    def _extract_attachments(self, message: dict[str, Any]) -> list[dict[str, str]]:
        """Extract attachment metadata from a message."""
        attachments = []
        parts = message.get("payload", {}).get("parts", [])

        for part in parts:
            filename = part.get("filename")
            if filename and part.get("body", {}).get("attachmentId"):
                attachments.append({
                    "filename": filename,
                    "mime_type": part.get("mimeType", ""),
                    "attachment_id": part["body"]["attachmentId"],
                    "size": part.get("body", {}).get("size", 0),
                })

        return attachments

    def _parse_date(self, date_str: str) -> str:
        """Parse email date string into YYYY-MM-DD format."""
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")

        # Try common email date formats
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %z",
            "%d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Fallback: try to extract date with regex
        match = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", date_str)
        if match:
            try:
                return datetime.strptime(match.group(1), "%d %b %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass

        print_warning(f"Could not parse date: {date_str}")
        return datetime.now().strftime("%Y-%m-%d")

    def _match_vendor(self, sender: str) -> str:
        """Match email sender to a configured vendor."""
        for vendor in self.config.vendors:
            if vendor.matches_email(sender):
                return vendor.name
        return "Unknown"
