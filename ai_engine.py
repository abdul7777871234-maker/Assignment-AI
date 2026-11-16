from __future__ import annotations

from typing import Iterator
import time


SYSTEM_PROMPT = """You are University Assignment AI, a precise academic writing and study assistant.
Help users understand questions, plan assignments, explain concepts, solve problems step by step,
and improve their writing. Preserve the user's intended meaning and factual details when rewriting.
Never invent citations, references, quotations, statistics, or source details. Clearly flag uncertainty
and ask for missing assignment requirements when essential. Use clear headings and structured answers.
When asked to humanize text, make it natural, fluent, and readable without changing its meaning; do not
claim to bypass AI detectors or guarantee any detector outcome. Support learning and academic integrity."""

DEFAULT_GEMINI_FALLBACKS = [
    "gemini-4-hydrogen",
    "gemini-4-carbon",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    # The public Gemini API endpoint uses this exact ID for Gemini 3 Flash.
    "gemini-3-flash-preview",
]


def _secret(secrets, key: str, default: str = "") -> str:
    try:
        return str(secrets.get(key, default)).strip()
    except Exception:
        return default


def _gemini_models(secrets) -> list[str]:
    primary = _secret(secrets, "GEMINI_MODEL", DEFAULT_GEMINI_FALLBACKS[0])
    configured = _secret(secrets, "GEMINI_FALLBACK_MODELS", "")
    fallbacks = [item.strip() for item in configured.split(",") if item.strip()] if configured else DEFAULT_GEMINI_FALLBACKS
    # Keep the selected primary first and avoid duplicate attempts.
    return list(dict.fromkeys([primary, *fallbacks]))


def _compact_messages(system: str, history: list[dict], attached_text: str = "") -> list[dict]:
    """Keep requests below the on-demand TPM budget while retaining recent context."""
    max_input_chars = 18000
    attachment_budget = 7000
    messages = _compact_messages(system, history, attached_text)

    errors: list[str] = []

    # Try Groq first. Buffer each provider's complete answer so a mid-stream
    # failure cannot leave partial text on screen before the fallback answer.
    if groq_key:
        try:
            from groq import Groq

            client = Groq(api_key=groq_key, timeout=90.0, max_retries=0)
            stream = client.chat.completions.create(
                model=groq_model,
                messages=messages,
                temperature=0.35,
                max_tokens=2000,
                stream=True,
            )
            parts: list[str] = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
            answer = "".join(parts).strip()
            if not answer:
                raise RuntimeError("Groq returned an empty response.")
            yield answer
            return
        except Exception as exc:
            errors.append(f"Groq ({groq_model}): {type(exc).__name__}: {exc}")

    # If Groq is down, rate-limited, times out, or returns no content,
    # automatically try Gemini models in the configured order.
    if gemini_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_key)
            prompt_messages = []
            for item in messages:
                role = "model" if item["role"] == "assistant" else "user"
                prompt_messages.append({"role": role, "parts": [{"text": item["content"]}]})

            for model in _gemini_models(secrets):
                try:
                    answer = ""
                    for attempt in range(2):
                        try:
                            response = client.models.generate_content_stream(
                                model=model,
                                contents=prompt_messages,
                            )
                            parts: list[str] = []
                            for chunk in response:
                                chunk_text = getattr(chunk, "text", None)
                                if chunk_text:
                                    parts.append(chunk_text)
                            answer = "".join(parts).strip()
                            if not answer:
                                raise RuntimeError("Gemini returned an empty response.")
                            break
                        except Exception as exc:
                            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                            transient = status in (429, 500, 502, 503, 504) or any(
                                marker in str(exc).lower() for marker in ("503", "unavailable", "high demand", "429", "resource exhausted")
                            )
                            if attempt == 0 and transient:
                                time.sleep(2)
                                continue
                            raise
                    if answer:
                        yield answer
                        return
                except Exception as exc:
                    errors.append(f"Gemini ({model}): {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"Gemini client: {type(exc).__name__}: {exc}")

    if not groq_key and not gemini_key:
        yield "AI providers are not configured. Add GROQ_API_KEY and/or GEMINI_API_KEY in Streamlit Secrets."
    else:
        yield (
            "All configured AI providers/models failed. Check API keys, model access, quotas, billing, "
            "and network access. The app tried Groq first, then the configured Gemini fallback models. "
            "Details: " + " | ".join(errors)
        )
