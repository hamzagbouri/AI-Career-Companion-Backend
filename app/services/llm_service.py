import json
import logging
import os
from typing import TypedDict

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:8b")


class CVAuditResult(TypedDict):
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    score: int


class LLMUnavailableError(Exception):
    """Raised when the LLM service (Ollama) is unavailable or returns an error."""

    pass


async def audit_cv_with_llm(extracted_text: str) -> CVAuditResult:
    """
    Call Ollama to analyse a CV and return structured feedback.
    """
    # Cap CV length to avoid OOM and speed up inference
    cv_snippet = (extracted_text or "")[:4000].strip()
    prompt = (
        "You are an AI career coach. Analyse the following CV text and respond "
        "STRICTLY as JSON with the keys: summary (string), strengths (array of strings), "
        "weaknesses (array of strings), recommendations (array of strings), score (integer 0-100).\n\n"
        f"CV TEXT:\n{cv_snippet}\n\n"
        "JSON RESPONSE:\n"
    )

    # Long read timeout: Ollama can take several minutes for llama3:8b
    timeout = httpx.Timeout(10.0, read=300.0)

    try:
        async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=timeout) as client:
            resp = await client.post(
                "/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            if resp.status_code >= 400:
                try:
                    err_body = resp.text
                    if len(err_body) > 500:
                        err_body = err_body[:500] + "..."
                    logger.warning(
                        "Ollama error status=%s body=%s",
                        resp.status_code,
                        err_body,
                    )
                except Exception:
                    pass
                raise LLMUnavailableError(
                    f"LLM service returned {resp.status_code}. "
                    "Ensure the model is pulled (e.g. ollama pull llama3:8b) and the container has enough memory."
                )
            data = resp.json()
            raw = data.get("response", "").strip()
    except httpx.TimeoutException as e:
        logger.warning("Ollama request timed out: %s", str(e))
        raise LLMUnavailableError(
            "LLM request timed out. Try again or use a shorter CV."
        ) from e
    except httpx.RequestError as e:
        logger.warning("Ollama request failed: %s", type(e).__name__ + " " + str(e))
        raise LLMUnavailableError("LLM service unreachable. Is Ollama running?") from e

    # Try to locate JSON in the response
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end != -1:
            raw = raw[start:end]
        parsed = json.loads(raw)
    except Exception:
        # Fallback: minimal structure
        parsed = {
            "summary": raw[:500],
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "score": 60,
        }

    return {
        "summary": str(parsed.get("summary", "")),
        "strengths": [str(s) for s in parsed.get("strengths", [])],
        "weaknesses": [str(w) for w in parsed.get("weaknesses", [])],
        "recommendations": [str(r) for r in parsed.get("recommendations", [])],
        "score": int(parsed.get("score", 60)),
    }

