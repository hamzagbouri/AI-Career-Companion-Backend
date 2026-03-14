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


class ExerciseGenerateResult(TypedDict):
    title: str
    description: str
    skeleton_code: str
    difficulty: str
    expected_solution: str


async def generate_exercise_with_llm(
    language: str,
    difficulty: str = "Beginner",
    topic: str = "basics",
) -> ExerciseGenerateResult:
    """Ask Ollama to generate one coding exercise for the given topic. Returns title, description, skeleton_code, difficulty, expected_solution."""
    prompt = (
        f"You are a programming teacher. Generate ONE coding exercise in {language}.\n"
        f"Difficulty: {difficulty}. Topic/focus: {topic} (e.g. OOP, dictionaries, tuples, lists, functions, loops, file I/O).\n"
        "Respond STRICTLY with a single JSON object with keys: "
        "title (string), description (string, 2-4 sentences explaining the task), "
        "skeleton_code (string, code with TODO or ... for the student to complete), "
        "difficulty (string: Beginner, Intermediate, or Advanced), "
        "expected_solution (string, the correct full code solution to the exercise).\n\n"
        "JSON only, no markdown:\n"
    )
    timeout = httpx.Timeout(10.0, read=120.0)
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=timeout) as client:
            resp = await client.post(
                "/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            if resp.status_code >= 400:
                logger.warning("Ollama exercise generate status=%s", resp.status_code)
                if resp.status_code == 404:
                    raise LLMUnavailableError(
                        f"Model '{OLLAMA_MODEL}' not found. Pull it in the Ollama container: ollama pull {OLLAMA_MODEL}"
                    )
                raise LLMUnavailableError(
                    f"LLM returned {resp.status_code}. Check Ollama and model."
                )
            data = resp.json()
            raw = data.get("response", "").strip()
    except httpx.TimeoutException as e:
        logger.warning("Ollama exercise generate timeout: %s", e)
        raise LLMUnavailableError("LLM request timed out.") from e
    except httpx.RequestError as e:
        logger.warning("Ollama exercise generate request failed: %s", e)
        raise LLMUnavailableError("LLM unreachable.") from e

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end != -1:
            raw = raw[start:end]
        parsed = json.loads(raw)
    except Exception:
        parsed = {
            "title": f"{language} {topic} exercise",
            "description": "Complete the code as described.",
            "skeleton_code": "# Write your code here\n",
            "difficulty": difficulty,
            "expected_solution": "# Solution\n",
        }
    return {
        "title": str(parsed.get("title", "Exercise")).strip() or "Exercise",
        "description": str(parsed.get("description", "")).strip() or "Complete the task.",
        "skeleton_code": str(parsed.get("skeleton_code", "")).strip() or "# Code here",
        "difficulty": str(parsed.get("difficulty", difficulty)).strip() or difficulty,
        "expected_solution": str(parsed.get("expected_solution", "")).strip() or "# Solution",
    }


class EvaluateResult(TypedDict):
    correct: bool
    feedback: str
    correct_answer: str


async def evaluate_submission_with_llm(
    language: str,
    description: str,
    expected_solution: str,
    submitted_code: str,
) -> EvaluateResult:
    """Ask Ollama whether the submitted code is correct. Returns correct, feedback, and correct_answer (if wrong)."""
    prompt = (
        f"You are a programming teacher. Exercise (in {language}):\n{description[:2000]}\n\n"
        f"Expected solution (reference):\n{expected_solution[:1500]}\n\n"
        f"Student submitted code:\n{submitted_code[:3000]}\n\n"
        "Is the student's solution correct? Respond STRICTLY with a JSON object: "
        "correct (boolean), feedback (string, brief explanation), "
        "correct_answer (string, the full correct code to show the student if incorrect; if correct use empty string).\n\n"
        "JSON only:\n"
    )
    timeout = httpx.Timeout(10.0, read=120.0)
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=timeout) as client:
            resp = await client.post(
                "/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            if resp.status_code >= 400:
                raise LLMUnavailableError(f"LLM returned {resp.status_code}")
            data = resp.json()
            raw = data.get("response", "").strip()
    except (httpx.TimeoutException, httpx.RequestError) as e:
        raise LLMUnavailableError("LLM unreachable or timeout.") from e
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end != -1:
            raw = raw[start:end]
        parsed = json.loads(raw)
    except Exception:
        parsed = {"correct": False, "feedback": "Could not evaluate.", "correct_answer": expected_solution}
    return {
        "correct": bool(parsed.get("correct", False)),
        "feedback": str(parsed.get("feedback", "")).strip() or "No feedback.",
        "correct_answer": str(parsed.get("correct_answer", "")).strip() or (expected_solution if not parsed.get("correct") else ""),
    }

