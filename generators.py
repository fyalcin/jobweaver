import os
import re
import time
import subprocess
import logging
import json
import random
import tempfile
import shutil
from typing import Optional, Tuple

import demo_mode
import model_transport
from operation_budget import operation, check, current, OperationTerminated, OperationBusy
from compiler_sandbox import run_tool

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SCRAPER_CONFIG_PATH = os.path.join(_ROOT, "scraper_config.json")


def _decode_process_output(value: bytes) -> str:
    """Decode tool output without letting locale-specific bytes abort generation."""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


class AIContentFilterError(RuntimeError):
    """Raised when the provider's moderation stops the generation mid-stream."""


class AITruncatedError(RuntimeError):
    """Raised when the response hit max_tokens (finish_reason=length)."""


def _routing(model_name: str, response_format: Optional[dict]) -> tuple[str, dict]:
    """Return (model, provider preferences) for an OpenRouter request.

    `:floor` (our "route cheapest" setting) sorts by price but also admits flex
    service-tier endpoints, which stalled calls for 60-155 s (Novita, 10.2026).
    Plain `sort: "price"` keeps the price order without flex. A structured-output
    request goes only to providers that support it (`require_parameters`).
    """
    provider = {}
    if model_name.endswith(":floor"):
        model_name = model_name[:-len(":floor")]
        provider["sort"] = "price"
    if response_format:
        provider["require_parameters"] = True
    return model_name, provider


MAX_OUTPUT_TOKENS = 8000


@operation()
def openrouter_api(prompt: str, model_name: str, label: str = "openrouter",
                   response_format: Optional[dict] = None) -> str:
    import requests
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is missing. Add it to .env, or choose a model from your own "
                         "OpenAI-compatible endpoint (custom/…, set CUSTOM_MODEL_BASE_URL) in Settings.")
    
    logger.info(f"[{label}] Calling OpenRouter API with model {model_name}...")
    t0 = time.time()
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_OUTPUT_TOKENS,
        # Hybrid reasoning models (e.g. z-ai/glm-5.3-flash) burn thousands of
        # thinking tokens out of max_tokens (measured: ~5,800 for a cover
        # letter), truncating the actual document (finish_reason=length).
        # Z.AI rejects reasoning {"enabled": false} with a 400, so cap the
        # thinking budget instead; non-reasoning models ignore the parameter.
        "reasoning": {"max_tokens": 1500},
    }
    payload["model"], provider = _routing(model_name, response_format)
    if provider:
        payload["provider"] = provider
    if response_format:
        payload["response_format"] = response_format
    resp = model_transport.post_json("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=300,
                                     label=label)
    if response_format and resp.status_code in (404, 429):
        # No allowed provider offers structured output right now (404: none
        # allowed by the account's provider settings; 429: the ones that do are
        # overloaded). Ask once without the schema within the same attempt budget;
        # the caller's own validation still applies and billing may be unknown.
        logger.warning(f"[{label}] Structured output unavailable ({resp.status_code}); retrying without schema")
        payload.pop("response_format")
        payload["provider"].pop("require_parameters")
        if not payload["provider"]:
            payload.pop("provider")
        resp = model_transport.post_json("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=300,
                                         label=label)
    if not resp.ok:
        err_msg = ""
        try:
            err_msg = resp.json().get("error", {}).get("message", "")
        except Exception:
            pass
        if err_msg:
            err_msg = _redact_endpoint_error(err_msg, "https://openrouter.ai/api/v1/chat/completions", headers)
            raise RuntimeError(f"OpenRouter error ({resp.status_code}): {err_msg}")
        resp.raise_for_status()
    data = resp.json()
    choice = data.get("choices", [{}])[0]
    if choice.get("finish_reason") == "content_filter":
        raise AIContentFilterError("OpenRouter response stopped by content filter")
    if choice.get("finish_reason") == "length":
        # Truncated output: LaTeX/json downstream would fail opaquely —
        # raise so run_ai_prompt's retry loop handles it visibly.
        raise AITruncatedError(f"[{label}] Response truncated at max_tokens (finish_reason=length)")
    elapsed = time.time() - t0
    
    content = data["choices"][0]["message"]["content"] or ""
    tier = data.get("service_tier")
    tier_info = f", service_tier={tier}" if tier and tier != "default" else ""
    logger.info(f"[{label}] Done in {elapsed:.1f}s ({len(content)} chars returned, provider={data.get('provider')}{tier_info})")
    
    return content


def _schema_in_prompt(prompt: str, response_format: dict) -> str:
    """For backends without structured output: ask for the JSON in the prompt; the caller still validates it."""
    schema = response_format.get("json_schema", {}).get("schema", {})
    return (prompt + "\n\nAnswer with ONLY one JSON object, no markdown fences and no commentary, "
            "that validates against this JSON Schema:\n" + json.dumps(schema))


def _extract_json_text(text: str) -> str:
    """Return the JSON object in `text`, dropping a markdown fence the model may add."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    return text


# --- any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, llama.cpp server, hosted APIs) ----------------

CUSTOM_PREFIX = "custom/"
_THINK_BLOCK = re.compile(r"^\s*<think>.*?</think>\s*", re.S)  # local reasoning models put this in the answer


def is_custom_model(model_name: Optional[str]) -> bool:
    return bool(model_name) and model_name.startswith(CUSTOM_PREFIX)


def _custom_base_url() -> str:
    base = os.environ.get("CUSTOM_MODEL_BASE_URL", "").strip().rstrip("/")
    return base[:-len("/chat/completions")] if base.endswith("/chat/completions") else base


def _custom_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("CUSTOM_MODEL_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _redact_endpoint_error(text, url, headers):
    """Provider error bodies can echo endpoint credentials; keep useful short errors."""
    from urllib.parse import urlsplit, parse_qsl
    parsed = urlsplit(url)
    secrets = [url, parsed.username, parsed.password, *(value for _, value in parse_qsl(parsed.query))]
    authorization = headers.get('Authorization', '')
    secrets += [authorization, authorization.removeprefix('Bearer ')]
    for value in sorted((value for value in secrets if value), key=len, reverse=True):
        text = text.replace(value, '[redacted]')
    return text[:300]


def _error_text(resp) -> str:
    try:
        data = resp.json()
    except Exception:
        return getattr(resp, "text", "") or ""
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if error:
        return str(error)
    return str(data.get("message") or data) if isinstance(data, dict) else str(data)


@operation()
def custom_model_api(prompt: str, model_name: str, label: str = "custom",
                     response_format: Optional[dict] = None) -> str:
    """One chat completion from the endpoint in CUSTOM_MODEL_BASE_URL (for example http://localhost:11434/v1).

    Only standard OpenAI parameters are sent. A server that refuses structured output is asked again with
    the schema in the prompt; one that refuses `max_tokens` (OpenAI's newer models) gets
    `max_completion_tokens`. The caller validates the answer in every case.
    """
    import requests
    base = _custom_base_url()
    if not base:
        raise ValueError("CUSTOM_MODEL_BASE_URL is not set. Add it to .env, for example "
                         "http://localhost:11434/v1 for Ollama or http://localhost:1234/v1 for LM Studio.")
    model = model_name[len(CUSTOM_PREFIX):]
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": MAX_OUTPUT_TOKENS}
    if response_format:
        payload["response_format"] = response_format
    logger.info(f"[{label}] Calling configured custom endpoint with model {model}...")
    t0 = time.time()
    for _ in range(3):  # at most two adjustments, each made once
        resp = model_transport.post_json(base + "/chat/completions", headers=_custom_headers(), json=payload, timeout=300,
                                         label=label)
        if resp.status_code not in (400, 422):
            break
        message = _error_text(resp).lower()
        if "max_tokens" in payload and "max_tokens" in message:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        elif "response_format" in payload and any(w in message for w in ("response_format", "json_schema", "schema")):
            logger.warning(f"[{label}] Endpoint refused structured output; asking with the schema in the prompt")
            payload.pop("response_format")
            payload["messages"][0]["content"] = _schema_in_prompt(prompt, response_format)
        else:
            break
    if not resp.ok:
        message = _redact_endpoint_error(_error_text(resp), base, _custom_headers())
        error = RuntimeError(f"Custom model endpoint error ({resp.status_code}): {message}")
        error.response = resp  # run_ai_prompt does not retry client errors
        raise error
    choice = (resp.json().get("choices") or [{}])[0]
    if choice.get("finish_reason") == "content_filter":
        raise AIContentFilterError("Custom endpoint response stopped by content filter")
    if choice.get("finish_reason") == "length":
        raise AITruncatedError(f"[{label}] Response truncated at the output limit (finish_reason=length)")
    content = _THINK_BLOCK.sub("", (choice.get("message") or {}).get("content") or "", count=1)
    if response_format:
        content = _extract_json_text(content)
    logger.info(f"[{label}] Done in {time.time() - t0:.1f}s ({len(content)} chars returned, custom endpoint)")
    return content


def list_custom_models() -> list[dict]:
    """Models the custom endpoint offers (GET /models), as {"id": "custom/<id>", "name": ...}; [] if unset or down."""
    import requests
    base = _custom_base_url()
    if not base:
        return []
    try:
        resp = requests.get(base + "/models", headers=_custom_headers(), timeout=5)
        resp.raise_for_status()
        entries = resp.json().get("data") or []
    except Exception as exc:
        logger.warning("Configured custom endpoint lists no models (%s)", type(exc).__name__)
        return []
    return [{"id": CUSTOM_PREFIX + str(m["id"]), "name": f"Custom endpoint: {m['id']}", "context_length": None}
            for m in entries if isinstance(m, dict) and m.get("id")]


def apply_route_cheapest(model: str, enabled: bool) -> str:
    """Append OpenRouter's :floor variant (price-sorted routing, admits flex endpoints).

    Idempotent; skipped for :free variants (no paid routing to optimize).
    """
    model = (model or "").strip()
    if not enabled or not model or model.endswith(":floor") or model.endswith(":free") or is_custom_model(model):
        return model
    return f"{model}:floor"


# Two model roles, deliberately separate:
#   openrouter_model -> high-volume pipeline work (one scoring call per scraped posting, ~50/day)
#   document_model   -> document generation (~2 calls per application)
# Before this split a single key did both, so improving the letters silently repriced scoring.
DEFAULT_SCRAPE_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_DOCUMENT_MODEL = "z-ai/glm-5.3-flash"


def resolve_scrape_model(config: Optional[dict]) -> str:
    """Model for high-volume pipeline work (scoring scraped postings). Cheap by default."""
    cfg = config or {}
    model = str(cfg.get("openrouter_model") or "").strip() or DEFAULT_SCRAPE_MODEL
    return apply_route_cheapest(model, bool(cfg.get("route_cheapest", False)))


def resolve_document_model(config: Optional[dict]) -> str:
    """Model for document generation, from the user's own `document_model` setting.

    Defaults to the same cheap model as scoring, so raising it is an explicit per-user choice
    with a visible price tag instead of a side effect of editing another key.
    """
    cfg = config or {}
    model = str(cfg.get("document_model") or "").strip() or DEFAULT_DOCUMENT_MODEL
    return apply_route_cheapest(model, bool(cfg.get("route_cheapest", False)))


@operation()
def run_ai_prompt(
    prompt: str,
    max_retries: int = 3,
    label: str = "openrouter",
    model_name: Optional[str] = None,
    response_format: Optional[dict] = None,
) -> str:
    """Run the model call (OpenRouter, or the custom endpoint for `custom/…` models) with retries."""
    demo_mode.refuse_if_enabled()
    delay = 2.0
    for attempt in range(max_retries):
        check()
        try:
            if is_custom_model(model_name):
                return custom_model_api(prompt, model_name, label, response_format=response_format)
            if response_format:
                return openrouter_api(prompt, model_name or "z-ai/glm-5.3-flash", label,
                                      response_format=response_format)
            return openrouter_api(prompt, model_name or "z-ai/glm-5.3-flash", label)
        except (AIContentFilterError, OperationTerminated):
            raise
        except Exception as e:
            response = getattr(e, 'response', None)
            status = getattr(response, 'status_code', None)
            if isinstance(e, (ValueError, TypeError)) or status in (400, 401, 403, 404, 422):
                raise
            if attempt < max_retries - 1:
                wait = delay + random.uniform(0, delay * 0.25)
                logger.warning(f"[{label}] API call failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait:.1f}s…")
                current().wait(wait)
                delay *= 2
            else:
                logger.error(f"[{label}] API call failed after {max_retries} attempts.")
                raise


@operation()
def research_company_sonar(
    company: str,
    role_title: str = "",
    description: str = "",
    model_name: str = "perplexity/sonar",
    label: str = "Company research"
) -> str:
    """
    Conduct live web-grounded company research via Perplexity Sonar on OpenRouter.
    Returns structured markdown findings with citations.
    """
    company = (company or "").strip()
    if not company:
        raise ValueError("Company name is required for research")

    role_context = f" for the role of '{role_title}'" if role_title else ""
    snippet = description[:1500].strip() if description else ""
    desc_context = f"\nJob posting excerpt:\n{snippet}\n" if snippet else ""

    prompt = f"""You are an elite corporate intelligence researcher assisting a job applicant applying to '{company}'{role_context}.

Conduct live web research on this company. Provide a concise, highly structured research briefing in Markdown format with the following sections:

## 1. Overview & Core Values
- Mission statement, core values, culture, and company identity.

## 2. Recent News & Developments
- Recent announcements, press releases, breakthroughs, funding, product launches, or acquisitions (from the past 12-24 months).

## 3. Key Products & Services
- What the company actually builds, sells, or operates; key customer segments.

## 4. Technology Stack & Engineering Signals
- Known technologies, architectures, developer culture, public repos, engineering blogs, or technical signals relevant to software/engineering roles.

## 5. Sources & Citations
- List all specific source URLs referenced in this research.

STRICT GROUNDING RULES:
- ONLY include facts that you can cite from verifiable web sources.
- If the company has a thin or limited web footprint (e.g., small local Austrian firm, early startup, public sector institution), explicitly state: "Public web information is limited for this organization" and summarize whatever basic facts are known, rather than generating generic or speculative corporate buzzwords.
- Never invent fictitious news, products, or values.
{desc_context}"""

    return run_ai_prompt(prompt, max_retries=2, label=label, model_name=model_name)

HUMANIZING_STRICT_INSTRUCTIONS = """
STRICT INSTRUCTION: Write like a human, not an AI. Use a natural, personal voice.
- Avoid common AI-generated writing patterns:
    * Do NOT use "AI vocabulary" like 'delve', 'pivotal', 'testament', 'vibrant', 'landscape', 'underscore', 'fostering', 'seamless', 'intricate', 'comprehensive', 'tailored', 'showcase' (unless absolutely necessary).
    * Avoid inflated symbolism or claims of "significance" and "legacy" (e.g., "stands as a testament", "marking a pivotal shift").
    * Avoid superficial "-ing" tack-ons (e.g., "...ensuring a seamless experience", "...highlighting my expertise").
    * Use simple copulas ("is", "are") instead of elaborate phrases like "serves as" or "boasts a".
- Vary sentence structure and rhythm:
    * Mix short, punchy sentences with longer ones. 
    * Avoid the "Rule of Three" (grouping points in sets of three) when it feels mechanical.
    * Do not start consecutive sentences with the same words (e.g., "I have", "I am", "Additionally").
- Be specific and concrete:
    * Replace vague buzzwords with actual results, specific technologies, or personal insights.
    * For motivational letters, sound like a real person with a genuine interest, not a corporate press release."""


def escape_latex(text):
    """
    Escapes LaTeX special characters in a string.
    """
    if not isinstance(text, str):
        return text
    # Order matters: backslash must be first
    replacements = [
        ('\\', r'\textbackslash{}'),
        ('&', r'\&'),
        ('%', r'\%'),
        ('$', r'\$'),
        ('#', r'\#'),
        ('_', r'\_'),
        ('{', r'\{'),
        ('}', r'\}'),
        ('~', r'\textasciitilde{}'),
        ('^', r'\textasciicircum{}'),
    ]
    mapping = dict(replacements)
    return ''.join(mapping.get(char, char) for char in text)

def write_latex(folder, filename, content):
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(content)
        return filepath
    except Exception as e:
        logger.error(f"Failed to write {filepath}: {e}")
        return None

@operation()
def _compile_fresh(folder, filename, output_filename, output_dir, engine, resource_dir=None):
    """Build in a fresh workspace; preserve source, logs and last-good PDF.

    Only explicit input files and public tool resources enter the native sandbox.
    """
    from pathlib import Path
    from document_artifacts import atomic_write, record_build, BUILD_TIMEOUT
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    name = Path(output_filename or filename).stem
    source = Path(folder, filename).read_text(encoding="utf-8")
    atomic_write(target / (name + '.pdf.attempt.json'), json.dumps({'success': False, 'source_hash': __import__('document_artifacts').digest(source)}))
    with tempfile.TemporaryDirectory(prefix="document-build-") as temp:
        build = Path(temp)
        for directory in (resource_dir, folder):
            if directory and Path(directory).is_dir():
                for item in Path(directory).iterdir():
                    if not item.is_symlink() and item.is_file() and item.suffix.lower() in ('.tex', '.typ', '.sty', '.cls', '.png', '.jpg', '.otf', '.ttf'):
                        shutil.copy2(item, build / item.name)
        input_path = build / Path(filename).name
        input_path.write_text(source, encoding="utf-8")
        pdf = build / (name + '.pdf')
        if engine == 'latex':
            command = ['pdflatex', '-no-shell-escape', '-halt-on-error', '-interaction=nonstopmode', f'-jobname={name}', str(input_path)]
        else:
            packages = Path(_ROOT, 'webapp/public/typst/packages')
            import re
            for package in re.findall(r'@([a-z]+/[\w-]+:[\d.]+)', source):
                path, version = package.split(':')
                if not (packages / path / version).is_dir():
                    return False, f'Offline Typst package unavailable: @{package}'
            command = ['typst', 'compile', '--diagnostic-format', 'short', '--root', str(build),
                       '--package-path', str(packages), '--package-cache-path', str(packages),
                       '--font-path', str(Path(_ROOT, 'webapp/public/typst/fonts')),
                       '--creation-timestamp', '0', str(input_path), str(pdf)]
        try:
            result = run_tool(command, build, assets=Path(_ROOT, 'webapp/public/typst') if engine == 'typst' else None,
                              timeout=BUILD_TIMEOUT)
            log = (_decode_process_output(result.stdout) + '\n' + _decode_process_output(result.stderr)).strip()
            atomic_write(target / (name + '.build.log'), log)
            if result.returncode != 0:
                return False, log or f'{engine} compilation failed (exit {result.returncode})'
            # Validation occurs before promotion; stale PDFs never enter the workspace.
            record = record_build(pdf, source, engine)
            check()
            atomic_write(target / (name + '.pdf'), pdf.read_bytes())
            atomic_write(target / (name + '.pdf.build.json'), json.dumps(record))
            atomic_write(target / (name + '.pdf.attempt.json'), json.dumps({'success': True, 'source_hash': record['source_hash']}))
            return True, 'PDF generated successfully.'
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            message = f'{engine} build failed: {exc}'
            atomic_write(target / (name + '.build.log'), message)
            return False, message


def compile_latex(folder, filename, output_filename=None, output_dir="outputs", resource_dir=None):
    return _compile_fresh(folder, filename, output_filename, output_dir, "latex", resource_dir)


def compile_typst(folder, filename, output_filename=None, output_dir=None, generate_previews=False, ppi=150):
    ok, message = _compile_fresh(folder, filename, output_filename, output_dir or folder, "typst")
    if ok and generate_previews:
        from pathlib import Path
        pdf = Path(output_dir or folder) / ((output_filename or filename).rsplit('.', 1)[0] + '.pdf')
        images = convert_pdf_to_images(str(pdf), output_dir or folder, "preview")
        if not images:
            message += " Preview generation failed; PDF remains available."
    return ok, message


def compile_studio_document(doc_dir):
    filename = "document.typ" if os.path.exists(os.path.join(doc_dir, "document.typ")) else "document.tex"
    return compile_typst(doc_dir, filename, "document.pdf", doc_dir, True) if filename.endswith('.typ') else compile_latex(doc_dir, filename, "document.pdf", doc_dir)

@operation()
def compile_latex_diff(folder, old_filename, new_filename, output_filename, output_dir="drafts", resource_dir=None):
    """Create and compile a diff in scratch space without writing templates."""
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix='document-diff-') as temp:
        build = Path(temp)
        for name in (old_filename, new_filename):
            shutil.copy2(Path(folder, name), build / name)
        try:
            result = run_tool(['latexdiff', old_filename, new_filename], build, timeout=45)
            if result.returncode != 0:
                return False, 'latexdiff failed: ' + _decode_process_output(result.stderr)
            (build / 'diff.tex').write_bytes(result.stdout)
            return compile_latex(str(build), 'diff.tex', output_filename, output_dir, resource_dir=resource_dir or folder)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f'Diff failed: {exc}'


@operation()
def convert_pdf_to_images(pdf_filepath: str, output_dir: str, prefix: str):
    """Render fresh pages; never combine a new PDF with old preview pages."""
    from pathlib import Path
    from document_artifacts import atomic_write
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='document-preview-') as temp:
        try:
            if Path(prefix).name != prefix:
                raise ValueError('Invalid preview filename')
            shutil.copy2(pdf_filepath, Path(temp, 'input.pdf'))
            result = run_tool(['pdftoppm', '-png', '-rx', '150', '-ry', '150', 'input.pdf', prefix], temp, timeout=45)
            if result.returncode != 0:
                logger.error('Preview failed: %s', _decode_process_output(result.stderr))
                return []
            images = sorted(Path(temp).glob(prefix + '-*.png'),
                            key=lambda image: int(image.stem.rsplit('-', 1)[1]))
            if not images:
                return []
            for image in images:
                atomic_write(output / image.name, image.read_bytes())
            names = {image.name for image in images}
            for old in output.glob(prefix + '-*.png'):
                if old.name not in names:
                    old.unlink()
            return [image.name for image in images]
        except OperationBusy as exc:
            # The PDF already exists; an optional preview must not fail it. Cancel/deadline stay terminal.
            logger.warning('Preview skipped: %s', exc)
            return []
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            logger.error('Preview failed: %s', exc)
            return []

def safe_latex(text: str) -> str:
    """Normalize model output before handing to pdflatex (does not escape valid TeX commands)."""
    if not isinstance(text, str):
        return text
    t = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    # Normalize Unicode quotation marks
    t = t.replace('“', "``").replace('”', "''").replace('„', ",,").replace('‟', "''")
    t = t.replace('‘', "`").replace('’', "'").replace('‚', ",")
    # Normalize Unicode dashes and hyphens
    t = t.replace('—', '---').replace('–', '--').replace('−', '-')
    # Normalize Unicode whitespace
    t = t.replace('\u00a0', ' ').replace('\u202f', ' ').replace('\u200b', '').replace('\ufeff', '')
    return t


def parse_pdflatex_error(log_content: str) -> dict:
    """Parse pdflatex stdout/log into a structured dictionary with line number and message."""
    if not log_content:
        return {"line": None, "message": "Unknown LaTeX compilation error", "snippet": "", "raw": ""}

    import re
    error_match = re.search(r"^!\s+(.+)$", log_content, re.MULTILINE)
    line_match = re.search(r"^l\.(\d+)\s*(.*)$", log_content, re.MULTILINE)

    line_number = int(line_match.group(1)) if line_match else None
    snippet = line_match.group(2).strip() if line_match else ""
    error_msg = error_match.group(1).strip() if error_match else "LaTeX compilation error"

    if line_number and snippet:
        friendly = f"Line {line_number}: {error_msg} (near '{snippet}')"
    elif line_number:
        friendly = f"Line {line_number}: {error_msg}"
    else:
        friendly = error_msg

    return {
        "line": line_number,
        "message": friendly,
        "error_type": error_msg,
        "snippet": snippet,
        "raw": log_content[:5000],
    }


def parse_typst_error(log_content: str) -> dict:
    """Parse typst CLI diagnostic output into a structured dictionary with line number and message."""
    if not log_content:
        return {"line": None, "column": None, "message": "Unknown Typst compilation error", "snippet": "", "raw": ""}

    import re
    # 1. Match short format: <file>:<line>:<col>: error: <msg>
    short_match = re.search(r'(?:^|\n)(?:[^\n:]+):(\d+):(\d+):\s*(?:error|warning):\s*(.+)', log_content)
    if short_match:
        line_num = int(short_match.group(1))
        col_num = int(short_match.group(2))
        err_msg = short_match.group(3).strip()
        return {
            "line": line_num,
            "column": col_num,
            "message": f"Line {line_num}: {err_msg}",
            "error_type": err_msg,
            "snippet": f"Column {col_num}",
            "raw": log_content[:5000],
        }

    # 2. Match human format: error: <msg>\n  ┌─ ...:<line>:<col>
    human_match = re.search(r'error:\s*(.+?)\n\s*┌─\s*[^:\n]+:(\d+):(\d+)', log_content)
    if human_match:
        err_msg = human_match.group(1).strip()
        line_num = int(human_match.group(2))
        col_num = int(human_match.group(3))
        snip_match = re.search(r'(\d+\s*│\s*.+)', log_content)
        snippet = snip_match.group(1).strip() if snip_match else f"Column {col_num}"
        return {
            "line": line_num,
            "column": col_num,
            "message": f"Line {line_num}: {err_msg}",
            "error_type": err_msg,
            "snippet": snippet,
            "raw": log_content[:5000],
        }

    # 3. Fallback: match general error: <msg>
    general_match = re.search(r'error:\s*(.+)', log_content)
    err_msg = general_match.group(1).strip() if general_match else log_content.splitlines()[0][:100]
    return {
        "line": None,
        "column": None,
        "message": err_msg,
        "error_type": err_msg,
        "snippet": "",
        "raw": log_content[:5000],
    }


@operation()
def ai_surgical_edit_typst(typst_code, instruction, selection=None, model_name="z-ai/glm-5.3-flash", user=None):
    from reviewed_documents import grounded_edit
    return grounded_edit(typst_code, instruction, user, model_name, run_ai_prompt)


@operation()
def ai_surgical_edit_latex(tex_code, instruction, selection=None, model_name="z-ai/glm-5.3-flash", user=None):
    from reviewed_documents import grounded_edit
    return grounded_edit(tex_code, instruction, user, model_name, run_ai_prompt)


HUMANIZING_DE_ADDENDUM = """
STRICT INSTRUCTION (German documents): Schreibe natürliches, menschliches Deutsch — kein KI-Deutsch.
- Vermeide typische KI-Floskeln und Werbesprache: 'nahtlos', 'innovativ', 'mit Leidenschaft', 'hochmotiviert', 'kreativ und lösungsorientiert', 'ich bringe mich mit Freude ein', 'Unterstützung bei', 'mit Blick auf', 'Polyvalenz'.
- Keine Adjektiv-Ketten aus drei oder mehr Eigenschaften (z. B. 'teamfähig, flexibel und belastbar') — maximal zwei, oder besser: konkrete Beispiele statt Adjektive.
- Vermeide Passiv-Konstruktionen und Nominal-Stau ('Die Sicherstellung einer hohen Servicequalität erfolgt durch…') — kurze, aktive Sätze mit 'ich'.
- Keine gestelzten Anglizismen oder eingedeutschte Business-Sprache ('Das ist ein Game-Changer', 'wir trudeln das aus').
- Schreibe wie eine reale Bewerberin oder ein realer Bewerber: klar, konkret, mit echten Beispielen — kein Marketing-Prospekt, keine Betroffenheitsfloskeln."""


@operation()
def refine_document_with_feedback(current_tex, feedback, model_name="z-ai/glm-5.3-flash", tone="", user=None):
    from reviewed_documents import grounded_edit
    return grounded_edit(current_tex, feedback, user, model_name, run_ai_prompt)


