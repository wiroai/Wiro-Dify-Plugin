"""Shared helpers for the Wiro AI model provider.

The provider only talks to the Wiro AI LLM gateway at https://llm.wiro.ai/v1.
The model list and every model's limits come from the gateway's own catalog
(GET /v1/models), which is free to call and checks the API key on the way.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import requests

GATEWAY_URL = "https://llm.wiro.ai/v1"
USER_AGENT = "wiro-dify-plugin/0.1.0 (+https://github.com/wiroai/Wiro-Dify-Plugin)"
MODELS_PAGE = "https://wiro.ai/models?categories=llm-tool-call"

# (connect, read) seconds for catalog calls. Model calls use the SDK timeout.
CATALOG_TIMEOUT = (10, 30)
CATALOG_CACHE_SECONDS = 600

MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")

# Used when the gateway publishes no value for a model.
DEFAULT_CONTEXT_SIZE = 128_000
DEFAULT_MAX_TOKENS = 8_192
MAX_TOKENS_DEFAULT_CAP = 8_192

# Models with at least this much context are offered for Dify agents.
AGENT_CONTEXT_FLOOR = 100_000

# Sampling controls that map one to one onto Dify's parameter templates.
TEMPLATE_CONTROLS = ("temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty")


class WiroGatewayError(Exception):
    """A catalog call failed. The message is safe to show to the user."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def bearer_token(credentials: Mapping[str, Any]) -> str:
    """Build the Bearer value: the key alone, or key:secret for signature projects."""
    key = str(credentials.get("api_key") or "").strip()
    secret = str(credentials.get("api_secret") or "").strip()
    if not key:
        raise WiroGatewayError("Enter the API key of your Wiro AI project.")
    if secret and ":" not in key:
        return f"{key}:{secret}"
    return key


def catalog_headers(credentials: Mapping[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer_token(credentials)}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _gateway_error(response: requests.Response) -> tuple[str, str | None]:
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:300], None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or "").strip(), error.get("code")
    return (response.text or "").strip()[:300], None


def check_key(credentials: Mapping[str, Any]) -> None:
    """Check the key with GET /v1/models, which spends nothing."""
    try:
        response = requests.get(
            f"{GATEWAY_URL}/models",
            params={"limit": 1},
            headers=catalog_headers(credentials),
            timeout=CATALOG_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WiroGatewayError("Could not reach the Wiro AI gateway. Check the network and try again.") from exc
    if response.status_code == 200:
        return
    message, code = _gateway_error(response)
    if response.status_code == 401:
        raise WiroGatewayError(
            "Wiro AI did not accept these credentials. Check the API key, and add the API secret "
            "if your project uses signature authentication.",
            401,
            code,
        )
    raise WiroGatewayError(
        f"Wiro AI answered with HTTP {response.status_code}: {message or 'no details'}",
        response.status_code,
        code,
    )


_model_cache: dict[str, tuple[float, dict | None]] = {}
_model_cache_lock = threading.Lock()


def fetch_model(model_id: str, credentials: Mapping[str, Any]) -> dict | None:
    """Return the gateway's catalog entry for one model, or None if the gateway does not list it."""
    now = time.monotonic()
    with _model_cache_lock:
        cached = _model_cache.get(model_id)
        if cached and now - cached[0] < CATALOG_CACHE_SECONDS:
            return cached[1]
    try:
        response = requests.get(
            f"{GATEWAY_URL}/models/{model_id}",
            headers=catalog_headers(credentials),
            timeout=CATALOG_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WiroGatewayError("Could not reach the Wiro AI gateway. Check the network and try again.") from exc
    if response.status_code == 200:
        entry = response.json()
    elif response.status_code == 404:
        entry = None
    else:
        message, code = _gateway_error(response)
        raise WiroGatewayError(
            f"Wiro AI answered with HTTP {response.status_code}: {message or 'no details'}",
            response.status_code,
            code,
        )
    with _model_cache_lock:
        _model_cache[model_id] = (now, entry)
    return entry


def per_million(value: Any) -> str | None:
    """Turn a USD-per-token string into a USD-per-million-tokens string."""
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value)) * Decimal(1_000_000)
    except ArithmeticError:
        return None
    text = format(amount.normalize(), "f")
    return text


def _positive_int(*values: Any) -> int | None:
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def model_schema(entry: Mapping[str, Any]) -> dict:
    """Build a Dify model schema (the same shape as a model YAML file) from a catalog entry."""
    model_id = str(entry["id"])
    caps = entry.get("capabilities") or {}
    supported = set(entry.get("supported_parameters") or [])
    controls = set(caps.get("generation_controls") or [])
    inputs = set(caps.get("input_modalities") or [])
    modes = [mode for mode in ("json_object", "json_schema") if mode in (caps.get("structured_output_modes") or [])]

    context_size = _positive_int(entry.get("context_length"), entry.get("max_input_tokens")) or DEFAULT_CONTEXT_SIZE
    max_tokens = (
        _positive_int(entry.get("max_tokens"), (entry.get("top_provider") or {}).get("max_completion_tokens"))
        or DEFAULT_MAX_TOKENS
    )

    features: list[str] = []
    if caps.get("function_tools"):
        features += ["tool-call", "multi-tool-call", "stream-tool-call"]
        if context_size >= AGENT_CONTEXT_FLOOR:
            features.append("agent-thought")
    if "image" in inputs:
        features.append("vision")
    if "document" in inputs:
        features.append("document")
    if caps.get("structured_outputs") and "json_schema" in modes:
        features.append("structured-output")

    rules: list[dict] = []
    for name in TEMPLATE_CONTROLS:
        if name in supported:
            rule: dict[str, Any] = {"name": name, "use_template": name}
            if name == "temperature":
                rule["max"] = 2.0
            rules.append(rule)
    rules.append(
        {
            "name": "max_tokens",
            "use_template": "max_tokens",
            "default": min(MAX_TOKENS_DEFAULT_CAP, max_tokens),
            "min": 1,
            "max": max_tokens,
        }
    )
    if "seed" in supported:
        rules.append(
            {
                "name": "seed",
                "label": {"en_US": "Seed"},
                "type": "int",
                "required": False,
                "help": {"en_US": "Send the same seed to get repeatable answers where the model supports it."},
            }
        )
    if "reasoning_effort" in supported:
        rules.append(
            {
                "name": "reasoning_effort",
                "label": {"en_US": "Reasoning effort"},
                "type": "string",
                "required": False,
                "options": ["low", "medium", "high"],
                "help": {
                    "en_US": "How much the model thinks before it answers. Lower is faster and uses fewer tokens."
                },
            }
        )
    if "verbosity" in controls:
        rules.append(
            {
                "name": "verbosity",
                "label": {"en_US": "Verbosity"},
                "type": "string",
                "required": False,
                "options": ["low", "medium", "high"],
                "help": {"en_US": "How long and detailed the answer should be."},
            }
        )
    if "response_format" in supported and modes:
        rules.append(
            {
                "name": "response_format",
                "label": {"en_US": "Response format"},
                "type": "string",
                "required": False,
                "options": ["text", *modes],
                "help": {
                    "en_US": "Ask for plain text, any valid JSON object, or JSON that follows a schema."
                    if "json_schema" in modes
                    else "Ask for plain text or any valid JSON object."
                },
            }
        )
        if "json_schema" in modes:
            rules.append({"name": "json_schema", "use_template": "json_schema"})

    schema: dict[str, Any] = {
        "model": model_id,
        "label": {"en_US": model_id},
        "model_type": "llm",
        "features": features,
        "model_properties": {"mode": "chat", "context_size": context_size},
        "parameter_rules": rules,
    }

    pricing = entry.get("pricing") or {}
    prompt_price = per_million(pricing.get("prompt"))
    completion_price = per_million(pricing.get("completion"))
    if prompt_price is not None and completion_price is not None:
        schema["pricing"] = {
            "input": prompt_price,
            "output": completion_price,
            "unit": "0.000001",
            "currency": "USD",
        }
    return schema


def fallback_schema(model_id: str) -> dict:
    """Schema for a model the catalog could not describe: text in, tools on, safe limits."""
    return model_schema(
        {
            "id": model_id,
            "context_length": DEFAULT_CONTEXT_SIZE,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "capabilities": {"function_tools": True, "input_modalities": ["text"]},
            "supported_parameters": ["temperature", "top_p"],
        }
    )
