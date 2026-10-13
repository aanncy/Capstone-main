"""Ways to reach a model. The rest of the app only sees ProviderChain.complete(system, user)."""
import logging
import os
import time

import base64

import httpx


log = logging.getLogger("app.providers")


class ProviderError(Exception):
    """A provider could not give an answer (rate limit, bad token, network...)."""


def text_only(user: str, attachments, provider: str) -> str:
    """For providers that cannot read files: put text files into the prompt, refuse PDFs and images."""
    for a in attachments:
        if not a.is_text:
            raise ProviderError(f"{provider} cannot read {a.mime} files. Set PROVIDERS=gemini in backend/.env.")
    texts = [f"--- {a.name} ---\n{a.data.decode('utf-8', errors='replace')}" for a in attachments]
    return "\n\n".join(texts + [user])


class GitHubModelsProvider:
    """GitHub Models REST API. Needs a token with the Models (read) permission."""
    name = "github_models"
    URL = "https://models.github.ai/inference/chat/completions"

    def __init__(self, token: str, model: str):
        self.token, self.model = token, model

    async def complete(self, system: str, user: str, attachments=()) -> str:
        user = text_only(user, attachments, "GitHub Models")
        if not self.token:
            raise ProviderError("GITHUB_TOKEN is not set. Add it to backend/.env.")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(self.URL, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"Could not reach GitHub Models: {e}") from e
        if r.status_code == 429:
            raise ProviderError("GitHub Models rate limit reached. Wait a minute and try again.")
        if r.status_code in (401, 403):
            raise ProviderError("GitHub rejected the token. Check GITHUB_TOKEN and its Models permission.")
        if r.status_code == 404:
            raise ProviderError(f"Model '{self.model}' was not found. Run: python -m scripts.try_it --list")
        if r.status_code >= 400:
            raise ProviderError(f"GitHub Models error {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError("GitHub Models sent a reply in an unexpected format.") from e


GEMINI_TIMEOUT = 300  # seconds; several long files in one request can take minutes (nginx allows 600)


class GeminiProvider:
    """Google Gemini API (free tier works). Needs an API key from https://aistudio.google.com/apikey"""
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str, thoughts: bool = False):
        self.api_key, self.model, self.thoughts = api_key, model, thoughts
        self.last_thoughts = None  # Gemini's summary of its reasoning for the last reply (if thoughts is on)

    async def complete(self, system: str, user: str, attachments=()) -> str:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not set. Add it to backend/.env.")
        self.last_thoughts = None
        files = []
        for a in attachments:  # name each file, so the model can tell the sources apart and cite them
            files += [{"text": f"File: {a.name}"},
                      {"inlineData": {"mimeType": a.mime, "data": base64.b64encode(a.data).decode("ascii")}}]
        config = {"temperature": 0.2, "responseMimeType": "application/json"}
        if self.thoughts:
            config["thinkingConfig"] = {"includeThoughts": True}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": files + [{"text": user}]}],
            "generationConfig": config,
        }
        try:
            async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
                r = await client.post(f"{self.BASE}/{self.model}:generateContent",
                                      headers={"x-goog-api-key": self.api_key}, json=body)
        except httpx.TimeoutException as e:
            raise ProviderError(f"Gemini did not answer within {GEMINI_TIMEOUT} seconds. Try again, or send fewer "
                                "or shorter files.") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"Could not reach Gemini: {e or type(e).__name__}") from e
        if r.status_code == 429:
            raise ProviderError("Gemini rate limit reached (free tier). Wait a minute and try again.")
        if r.status_code in (400, 401, 403) and "API key" in r.text:
            raise ProviderError("Gemini rejected the API key. Check GEMINI_API_KEY.")
        if r.status_code == 404:
            raise ProviderError(f"Gemini model '{self.model}' is not available: {r.text[:300]} "
                                "Pick another with: python -m scripts.try_it --list")
        if r.status_code >= 400:
            raise ProviderError(f"Gemini error {r.status_code}: {r.text[:200]}")
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            # Thought-summary parts are flagged "thought": true; keep them out of the answer
            self.last_thoughts = "\n\n".join(p.get("text", "") for p in parts if p.get("thought")) or None
            return "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError("Gemini sent a reply in an unexpected format (possibly blocked by safety filters).") from e


class CopilotSdkProvider:
    """GitHub Copilot SDK. UNTESTED: the SDK's Python calls changed between versions.
    Check the current getting-started page and adjust complete() if needed.
    Needs: pip install github-copilot-sdk, and the Copilot CLI signed in on this machine."""
    name = "copilot_sdk"

    def __init__(self, model: str):
        self.model = model

    async def complete(self, system: str, user: str, attachments=()) -> str:
        user = text_only(user, attachments, "Copilot SDK")
        try:
            from copilot import CopilotClient  # type: ignore
        except ImportError as e:
            raise ProviderError("github-copilot-sdk is not installed.") from e
        try:
            async with CopilotClient() as client:
                session = await client.create_session({"model": self.model})
                event = await session.send_and_wait({"prompt": f"{system}\n\n{user}"}, timeout=120)
        except Exception as e:  # SDK errors vary by version
            raise ProviderError(f"Copilot SDK failed: {e}") from e
        text = _event_text(event)
        if not text:
            raise ProviderError("Copilot SDK returned no text. Inspect the event object and update _event_text().")
        return text


def _event_text(event) -> str:
    for path in (("data", "content"), ("content",), ("text",)):
        obj = event
        for attr in path:
            obj = getattr(obj, attr, None)
            if obj is None:
                break
        if isinstance(obj, str) and obj.strip():
            return obj
    return ""


class ProviderChain:
    """Tries each provider in order and uses the first that answers."""

    def __init__(self, providers: list):
        self.providers = providers
        self.calls = 0  # model calls made, including fix-up retries
        self.used = None  # "provider/model" that gave the last answer
        self.thoughts = None  # reasoning summary for the last answer, if that provider gives one

    async def complete(self, system: str, user: str, attachments=()) -> str:
        problems = []
        self.calls += 1
        self.thoughts = None
        for p in self.providers:
            start = time.monotonic()
            try:
                reply = await p.complete(system, user, attachments)
            except ProviderError as e:
                log.warning("%s failed after %.1fs: %s", p.name, time.monotonic() - start, e)
                problems.append(f"{p.name}: {e}")
                continue
            self.used = f"{p.name}/{getattr(p, 'model', '?')}"
            self.thoughts = getattr(p, "last_thoughts", None)
            log.info("%s answered in %.1fs (%d chars)", p.name, time.monotonic() - start, len(reply))
            return reply
        raise ProviderError(" | ".join(problems) or "No AI provider is configured.")


def build_providers_from_env() -> ProviderChain:
    chosen = [p.strip() for p in os.getenv("PROVIDERS", "github_models").split(",") if p.strip()]
    providers = []
    for name in chosen:
        if name == "github_models":
            providers.append(GitHubModelsProvider(os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_MODEL", "openai/gpt-4.1")))
        elif name == "gemini":
            providers.append(GeminiProvider(os.getenv("GEMINI_API_KEY", ""), os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
                                            os.getenv("GEMINI_THOUGHTS", "true").lower() != "false"))
        elif name == "copilot_sdk":
            providers.append(CopilotSdkProvider(os.getenv("COPILOT_MODEL", "gpt-4.1")))
    return ProviderChain(providers)
