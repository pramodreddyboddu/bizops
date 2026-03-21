"""Anthropic Claude API client for AI-powered business insights."""

from __future__ import annotations

import os
from collections.abc import Generator


class AgentClient:
    """Client for querying Claude via the Anthropic Python SDK.

    Uses streaming by default for responsive terminal output.
    """

    MODEL = "claude-sonnet-4-20250514"
    MAX_TOKENS = 1024

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key not found. "
                "Set the ANTHROPIC_API_KEY environment variable or pass api_key= directly.\n"
                "  export ANTHROPIC_API_KEY='sk-ant-...'"
            )
        self._client = self._build_client()

    def _build_client(self):
        """Lazily import and build the Anthropic client."""
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for AI features.\n"
                "Install it with: pip install 'bizops[agent]'"
            )
        return anthropic.Anthropic(api_key=self.api_key)

    def query(self, system_prompt: str, user_message: str) -> str:
        """Send a message to Claude and return the full response text.

        Args:
            system_prompt: System instructions providing context.
            user_message: The user's question or request.

        Returns:
            The assistant's response as a string.
        """
        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        # Extract text from content blocks
        return "".join(
            block.text for block in response.content if hasattr(block, "text")
        )

    def stream_query(
        self, system_prompt: str, user_message: str
    ) -> Generator[str, None, None]:
        """Stream a response from Claude, yielding text chunks.

        Args:
            system_prompt: System instructions providing context.
            user_message: The user's question or request.

        Yields:
            Text chunks as they arrive from the API.
        """
        with self._client.messages.stream(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            yield from stream.text_stream
