import json
import logging
import os
import random
import re
from typing import TypedDict

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:8b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_GEMINI_MODEL_FALLBACKS_RAW = os.getenv("GEMINI_MODEL_FALLBACKS", "")


def _get_gemini_model_candidates() -> list[str]:
    """
    Ordered Gemini model candidates for failover.

    Primary model is GEMINI_MODEL. Fallbacks come from GEMINI_MODEL_FALLBACKS (comma-separated),
    otherwise we use a conservative default set of text-output models.
    """
    primary = (GEMINI_MODEL or "").strip()
    fallbacks = [m.strip() for m in (_GEMINI_MODEL_FALLBACKS_RAW or "").split(",") if m.strip()]
    if not fallbacks:
        fallbacks = [
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2-flash",
            "gemini-2-flash-exp",
            "gemini-2-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-3.1-pro",
            "gemini-3.1-flash-lite",
        ]

    seen: set[str] = set()
    ordered: list[str] = []
    for m in [primary, *fallbacks]:
        if not m or m in seen:
            continue
        seen.add(m)
        ordered.append(m)
    return ordered


class CVAuditResult(TypedDict):
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    score: int


class LLMUnavailableError(Exception):
    """Raised when the LLM service (Ollama) is unavailable or returns an error."""

    pass


def _extract_text_from_gemini_response(data: dict) -> str:
    """
    Safely extract text from Gemini response candidates.
    """
    if not isinstance(data, dict):
        return ""

    candidates = data.get("candidates") or []
    if not candidates:
        return ""

    candidate = candidates[0] or {}
    content = candidate.get("content") or {}
    parts = content.get("parts") or []

    texts = []
    for part in parts:
        if isinstance(part, dict) and "text" in part and part["text"]:
            texts.append(part["text"])

    return "\n".join(texts).strip()


async def generate_exercise_with_gemini(language: str, difficulty: str = "Beginner", topic: str = "basics"):
    if not GEMINI_API_KEY:
        raise LLMUnavailableError("GEMINI_API_KEY is not set")

    prompt = (
        f"You are a programming teacher. Generate ONE coding exercise in {language}. "
        f"Difficulty: {difficulty}. Topic/focus: {topic}. "
        "Return only valid JSON matching the requested schema."
    )

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "skeleton_code": {"type": "string"},
            "difficulty": {"type": "string"},
            "expected_solution": {"type": "string"},
        },
        "required": [
            "title",
            "description",
            "skeleton_code",
            "difficulty",
            "expected_solution",
        ],
        "additionalProperties": False,
    }

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 5000,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    gemini_models = _get_gemini_model_candidates()
    last_error: str = "Unknown Gemini error"

    for model in gemini_models:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=120.0)) as client:
                resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code >= 400:
                last_error = f"Gemini model={model} returned {resp.status_code}: {resp.text[:500]}"
                logger.warning(last_error)
                continue

            data = resp.json()

            text = _extract_text_from_gemini_response(data)
            if not text:
                candidate = ((data.get("candidates") or [{}])[0] if isinstance(data, dict) else {})
                finish_reason = candidate.get("finishReason")
                safety_ratings = candidate.get("safetyRatings")
                last_error = (
                    f"Gemini model={model} returned empty text. "
                    f"finishReason={finish_reason}, safetyRatings={safety_ratings}"
                )
                logger.warning(last_error)
                continue

            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                last_error = f"Gemini model={model} returned non-JSON text: {text[:300]!r}"
                logger.warning(last_error)
                continue

            return parsed

        except httpx.TimeoutException as e:
            last_error = f"Gemini model={model} timeout: {e}"
            logger.warning(last_error)
            continue
        except httpx.HTTPError as e:
            last_error = f"Gemini model={model} HTTP error: {e}"
            logger.warning(last_error)
            continue
        except Exception as e:
            last_error = f"Gemini model={model} failure: {e}"
            logger.warning(last_error)
            continue

    raise LLMUnavailableError(f"Gemini generation failed for all models. Last error: {last_error}")


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


def _template_exercise_payload(language: str, difficulty: str, topic: str) -> dict:
    """Concrete exercise dict when Ollama errors, times out, or returns invalid JSON."""
    lang = (language or "").lower()
    t = (topic or "").lower().strip()
    if lang == "python":
        # Topic-dependent templates so the UI doesn't repeat the same "sum" exercise.
        if t == "variables and data types":
            templates = [
                {
                    "title": "Python: detect a value type",
                    "description": "Write type_name(x) that returns the type name of x as a string.",
                    "skeleton_code": (
                        "def type_name(x) -> str:\n"
                        "    # TODO: return the type name of x\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "def type_name(x) -> str:\n"
                        "    return type(x).__name__\n"
                    ),
                }
            ]
            return random.choice(templates)

        if t == "functions":
            templates = [
                {
                    "title": "Python: repeat text with a function",
                    "description": "Write repeat_text(s, n) that repeats s exactly n times.",
                    "skeleton_code": (
                        "def repeat_text(s: str, n: int) -> str:\n"
                        "    # TODO: repeat s n times\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "def repeat_text(s: str, n: int) -> str:\n"
                        "    return s * n\n"
                    ),
                },
                {
                    "title": "Python: sum list using a function",
                    "description": "Write sum_list(nums) that returns the sum of integers in nums.",
                    "skeleton_code": (
                        "from typing import List\n\n"
                        "def sum_list(nums: List[int]) -> int:\n"
                        "    # TODO: return the sum\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "from typing import List\n\n"
                        "def sum_list(nums: List[int]) -> int:\n"
                        "    return sum(nums)\n"
                    ),
                },
            ]
            return random.choice(templates)

        if t == "loops":
            templates = [
                {
                    "title": "Python: sum from 1 to n",
                    "description": "Write sum_to_n(n) that returns 1 + 2 + ... + n.",
                    "skeleton_code": (
                        "def sum_to_n(n: int) -> int:\n"
                        "    # TODO: compute the sum using a loop\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "def sum_to_n(n: int) -> int:\n"
                        "    total = 0\n"
                        "    for i in range(1, n + 1):\n"
                        "        total += i\n"
                        "    return total\n"
                    ),
                },
                {
                    "title": "Python: count vowels",
                    "description": "Write count_vowels(s) that counts vowels (a,e,i,o,u) in the string s.",
                    "skeleton_code": (
                        "def count_vowels(s: str) -> int:\n"
                        "    # TODO: count vowels\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "def count_vowels(s: str) -> int:\n"
                        "    vowels = set('aeiou')\n"
                        "    return sum(1 for ch in s.lower() if ch in vowels)\n"
                    ),
                },
            ]
            return random.choice(templates)

        if t == "lists":
            templates = [
                {
                    "title": "Python: filter even numbers",
                    "description": "Write evens(nums) that returns a list of even integers from nums.",
                    "skeleton_code": (
                        "from typing import List\n\n"
                        "def evens(nums: List[int]) -> List[int]:\n"
                        "    # TODO: return a list of evens\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "from typing import List\n\n"
                        "def evens(nums: List[int]) -> List[int]:\n"
                        "    return [n for n in nums if n % 2 == 0]\n"
                    ),
                }
            ]
            return random.choice(templates)

        if t == "dictionaries":
            templates = [
                {
                    "title": "Python: frequency count",
                    "description": "Write frequencies(items) that returns a dict mapping each item to its count.",
                    "skeleton_code": (
                        "from typing import Any\n\n"
                        "def frequencies(items: list[Any]) -> dict[Any, int]:\n"
                        "    # TODO: count occurrences\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "from typing import Any\n\n"
                        "def frequencies(items: list[Any]) -> dict[Any, int]:\n"
                        "    result: dict[Any, int] = {}\n"
                        "    for x in items:\n"
                        "        result[x] = result.get(x, 0) + 1\n"
                        "    return result\n"
                    ),
                }
            ]
            return random.choice(templates)

        if t == "tuples":
            templates = [
                {
                    "title": "Python: swap tuple ends",
                    "description": "Write swap_ends(t) that swaps the first and last element of tuple t.",
                    "skeleton_code": (
                        "from typing import Any\n\n"
                        "def swap_ends(t: tuple[Any, ...]) -> tuple[Any, ...]:\n"
                        "    # TODO: swap first and last\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "from typing import Any\n\n"
                        "def swap_ends(t: tuple[Any, ...]) -> tuple[Any, ...]:\n"
                        "    if len(t) < 2:\n"
                        "        return t\n"
                        "    return (t[-1],) + t[1:-1] + (t[0],)\n"
                    ),
                }
            ]
            return random.choice(templates)

        if t == "oop":
            templates = [
                {
                    "title": "Python: mini class (BankAccount)",
                    "description": "Create class BankAccount with deposit and withdraw methods.",
                    "skeleton_code": (
                        "class BankAccount:\n"
                        "    def __init__(self, starting_balance: float = 0.0):\n"
                        "        # TODO\n"
                        "        self.balance = 0.0\n\n"
                        "    def deposit(self, amount: float) -> float:\n"
                        "        # TODO: add amount and return new balance\n"
                        "        return self.balance\n\n"
                        "    def withdraw(self, amount: float) -> float:\n"
                        "        # TODO: subtract amount and return new balance\n"
                        "        return self.balance\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "class BankAccount:\n"
                        "    def __init__(self, starting_balance: float = 0.0):\n"
                        "        self.balance = float(starting_balance)\n\n"
                        "    def deposit(self, amount: float) -> float:\n"
                        "        self.balance += float(amount)\n"
                        "        return self.balance\n\n"
                        "    def withdraw(self, amount: float) -> float:\n"
                        "        self.balance -= float(amount)\n"
                        "        return self.balance\n"
                    ),
                }
            ]
            return random.choice(templates)

        if t == "error handling":
            templates = [
                {
                    "title": "Python: safe division",
                    "description": "Write safe_div(a, b) that returns a / b, or None when b is 0.",
                    "skeleton_code": (
                        "def safe_div(a: float, b: float):\n"
                        "    # TODO: handle division by zero\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "def safe_div(a: float, b: float):\n"
                        "    if b == 0:\n"
                        "        return None\n"
                        "    return a / b\n"
                    ),
                }
            ]
            return random.choice(templates)

        if t == "file i/o":
            templates = [
                {
                    "title": "Python: read first line",
                    "description": "Write read_first_line(path) that returns the first line of the file as a string.",
                    "skeleton_code": (
                        "def read_first_line(path: str) -> str:\n"
                        "    # TODO: open the file and return the first line\n"
                        "    pass\n"
                    ),
                    "difficulty": "Beginner",
                    "expected_solution": (
                        "def read_first_line(path: str) -> str:\n"
                        "    with open(path, 'r', encoding='utf-8') as f:\n"
                        "        return f.readline().rstrip('\\n')\n"
                    ),
                }
            ]
            return random.choice(templates)

        # Default topic: basics (small arithmetic / list processing, but not only sum)
        templates = [
            {
                "title": "Python basics: max of two numbers",
                "description": "Write max_of_two(a, b) that returns the larger value.",
                "skeleton_code": (
                    "def max_of_two(a: int, b: int) -> int:\n"
                    "    # TODO: return the larger of a and b\n"
                    "    pass\n"
                ),
                "difficulty": "Beginner",
                "expected_solution": (
                    "def max_of_two(a: int, b: int) -> int:\n"
                    "    return a if a >= b else b\n"
                ),
            },
            {
                "title": "Python basics: reverse a list",
                "description": "Write reverse_list(nums) that returns a new list with items in reverse order.",
                "skeleton_code": (
                    "from typing import List\n\n"
                    "def reverse_list(nums: List[int]) -> List[int]:\n"
                    "    # TODO: return reversed copy\n"
                    "    pass\n"
                ),
                "difficulty": "Beginner",
                "expected_solution": (
                    "from typing import List\n\n"
                    "def reverse_list(nums: List[int]) -> List[int]:\n"
                    "    return list(reversed(nums))\n"
                ),
            },
        ]
        return random.choice(templates)
    if lang == "javascript":
        if t == "lists":
            return {
                "title": "JavaScript: filter even numbers",
                "description": "Write evens(nums) that returns an array containing only the even integers.",
                "skeleton_code": (
                    "function evens(nums) {\n"
                    "  // TODO: return evens\n"
                    "  return [];\n"
                    "}\n"
                ),
                "difficulty": "Beginner",
                "expected_solution": (
                    "function evens(nums) {\n"
                    "  return nums.filter(n => n % 2 === 0);\n"
                    "}\n"
                ),
            }
        if t == "functions":
            return {
                "title": "JavaScript: repeat text",
                "description": "Write repeatText(s, n) that repeats s exactly n times.",
                "skeleton_code": (
                    "function repeatText(s, n) {\n"
                    "  // TODO: return s repeated n times\n"
                    "  return '';\n"
                    "}\n"
                ),
                "difficulty": "Beginner",
                "expected_solution": (
                    "function repeatText(s, n) {\n"
                    "  return s.repeat(n);\n"
                    "}\n"
                ),
            }
        return {
            "title": "JavaScript basics: add two numbers",
            "description": "Write addNumbers(a, b) that returns a + b.",
            "skeleton_code": (
                "function addNumbers(a, b) {\n"
                "  // TODO: return the sum\n"
                "}\n"
            ),
            "difficulty": "Beginner",
            "expected_solution": (
                "function addNumbers(a, b) {\n"
                "  return a + b;\n"
                "}\n"
            ),
        }
    if lang == "java":
        return {
            "title": "Java basics: add two integers",
            "description": (
                "Complete the method addTwo(int a, int b) so that it returns the sum of a and b."
            ),
            "skeleton_code": (
                "public int addTwo(int a, int b) {\n"
                "    // TODO: return a + b\n"
                "    return 0;\n"
                "}\n"
            ),
            "difficulty": "Beginner",
            "expected_solution": (
                "public int addTwo(int a, int b) {\n"
                "    return a + b;\n"
                "}\n"
            ),
        }
    return {
        "title": f"{language} {topic} exercise",
        "description": (
            f"Implement a function in {language} that solves the task described in the starter code comments. "
            "Complete the function and return the correct result."
        ),
        "skeleton_code": "// TODO: implement the required function here\n",
        "difficulty": difficulty,
        "expected_solution": "// Correct solution\n",
    }


def _finalize_exercise_result(parsed: dict, language: str, difficulty: str) -> ExerciseGenerateResult:
    lang = language.lower()
    raw_desc = str(parsed.get("description", "")).strip()
    raw_skel = str(parsed.get("skeleton_code", "")).strip()
    generic_descs = ("complete the code as described", "complete the task described", "implement a simple function")
    if not raw_desc or any(g in raw_desc.lower() for g in generic_descs):
        if lang == "python":
            raw_desc = "Write a function that solves the task. Use the starter code and return the expected result."
        elif lang == "javascript":
            raw_desc = "Complete the function in the starter code so it returns the correct result."
        else:
            raw_desc = f"Complete the {language} function in the starter code and return the correct result."
    if not raw_skel:
        raw_skel = "# TODO: complete the code here" if lang == "python" else "// TODO: complete the code here"

    return {
        "title": str(parsed.get("title", "Exercise")).strip() or "Exercise",
        "description": raw_desc,
        "skeleton_code": raw_skel,
        "difficulty": str(parsed.get("difficulty", difficulty)).strip() or difficulty,
        "expected_solution": str(parsed.get("expected_solution", "")).strip()
        or "# Solution",
    }


async def generate_exercise_with_llm(
    language: str,
    difficulty: str = "Beginner",
    topic: str = "basics",
) -> ExerciseGenerateResult:
    """Ask Ollama for one exercise; on HTTP 500, timeout, or bad JSON use templates (still returns 200)."""
    # If Gemini is configured, it can provide more variety and speed than the local Ollama.
    if GEMINI_API_KEY:
        try:
            logger.info("Generating exercise with Gemini model=%s", GEMINI_MODEL)
            return await generate_exercise_with_gemini(
                language=language, difficulty=difficulty, topic=topic
            )
        except Exception as e:
            logger.warning("Gemini generation failed, falling back to Ollama: %s", e)

    prompt = (
        f"You are a programming teacher. Generate ONE coding exercise in {language}.\n"
        f"Difficulty: {difficulty}. Topic/focus: {topic}.\n"
        "Respond STRICTLY with a single JSON object (no markdown) with keys: "
        "title (string), "
        "description (string, 1-2 short sentences), "
        "skeleton_code (string, starter code only; student completes TODO), "
        "difficulty (string), "
        "expected_solution (string, only the correct code for the function/part; no explanations).\n\n"
        "JSON only. Keep everything concise."
    )
    # CPU inference often needs >30s; Ollama may return 500 when overloaded — templates keep the app usable.
    timeout = httpx.Timeout(30.0, read=240.0)
    raw = ""
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=timeout) as client:
            resp = await client.post(
                "/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 256, "temperature": 0.2},
                },
            )
            if resp.status_code == 404:
                raise LLMUnavailableError(
                    f"Model '{OLLAMA_MODEL}' not found. Pull it in the Ollama container: ollama pull {OLLAMA_MODEL}"
                )
            if resp.status_code >= 400:
                snippet = (resp.text or "")[:600].replace("\n", " ")
                logger.warning(
                    "Ollama exercise generate status=%s body=%s — using template fallback",
                    resp.status_code,
                    snippet,
                )
                payload = _template_exercise_payload(language, difficulty, topic)
                return _finalize_exercise_result(payload, language, difficulty)
            data = resp.json()
            raw = data.get("response", "").strip()
    except httpx.TimeoutException as e:
        logger.warning(
            "Ollama exercise generate timeout after long wait: %s — using template fallback",
            e,
        )
        payload = _template_exercise_payload(language, difficulty, topic)
        return _finalize_exercise_result(payload, language, difficulty)
    except httpx.RequestError as e:
        logger.warning("Ollama exercise generate request failed: %s — using template fallback", e)
        payload = _template_exercise_payload(language, difficulty, topic)
        return _finalize_exercise_result(payload, language, difficulty)

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end != -1:
            raw = raw[start:end]
        parsed = json.loads(raw)
    except Exception:
        logger.info("Exercise JSON parse failed, using template fallback")
        payload = _template_exercise_payload(language, difficulty, topic)
        return _finalize_exercise_result(payload, language, difficulty)

    return _finalize_exercise_result(parsed, language, difficulty)


class EvaluateResult(TypedDict):
    correct: bool
    feedback: str
    correct_answer: str


async def evaluate_submission_with_gemini(
    language: str,
    description: str,
    expected_solution: str,
    submitted_code: str,
) -> EvaluateResult:
    """
    Gemini-based submission evaluator.

    It only asks Gemini for {correct:boolean, feedback:string} to keep output small and avoid
    invalid/truncated JSON. The router uses expected_solution as the "correct answer" to show.
    """
    if not GEMINI_API_KEY:
        raise LLMUnavailableError("GEMINI_API_KEY is not set")

    # Keep the payload small to avoid Gemini truncating JSON.
    desc = (description or "").strip()[:2000]
    ref = (expected_solution or "").strip()[:2500]
    stu = (submitted_code or "").strip()[:5000]

    schema = {
        "type": "object",
        "properties": {
            "correct": {"type": "boolean"},
            "feedback": {"type": "string"},
        },
        "required": ["correct", "feedback"],
        "additionalProperties": False,
    }

    prompt = (
        "You are a programming teacher and code reviewer.\n"
        f"Language: {language}\n\n"
        f"Problem description:\n{desc}\n\n"
        f"Reference solution:\n{ref}\n\n"
        f"Student submission:\n{stu}\n\n"
        "Return ONLY a valid JSON object that matches the schema.\n"
        "Rules:\n"
        "- correct=true only if the student submission matches the reference solution.\n"
        "- feedback must be short (max 200 characters).\n"
        "- No markdown. No extra text."
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 400,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    gemini_models = _get_gemini_model_candidates()
    last_error: str = "Unknown Gemini error"

    for model in gemini_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=60.0)) as client:
                resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code >= 400:
                last_error = f"Gemini model={model} returned {resp.status_code}: {resp.text[:400]}"
                logger.warning(last_error)
                continue

            data = resp.json()
            text = _extract_text_from_gemini_response(data)
            if not text:
                last_error = f"Gemini model={model} returned empty content"
                logger.warning(last_error)
                continue

            parsed = json.loads(text)
            correct = bool(parsed.get("correct", False))
            feedback = str(parsed.get("feedback", "")).strip() or "No feedback."

            return {
                "correct": correct,
                "feedback": feedback,
                # Router expects a full correct answer when not correct.
                "correct_answer": "" if correct else expected_solution,
            }
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            last_error = f"Gemini model={model} invalid JSON: {e}"
            logger.warning(last_error)
            continue
        except httpx.HTTPError as e:
            last_error = f"Gemini model={model} request failed: {e}"
            logger.warning(last_error)
            continue
        except Exception as e:
            last_error = f"Gemini model={model} failure: {e}"
            logger.warning(last_error)
            continue

    raise LLMUnavailableError(f"Gemini evaluation failed for all models. Last error: {last_error}")


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
    timeout = httpx.Timeout(10.0, read=300.0)
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=timeout) as client:
            resp = await client.post(
                "/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 1024},
                },
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

