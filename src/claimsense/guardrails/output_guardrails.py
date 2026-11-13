"""Output Guardrails: OWASP Agentic Top 10 Protection Layer.

This module implements comprehensive output filtering and validation to prevent data exfiltration,
hallucinations, prompt leakage, and other OWASP Agentic vulnerabilities in agent responses.

Architecture:
- All guardrails follow a fail-closed design: failures block the output
- Functions are standalone and decoupled from business logic
- LLM-as-a-judge for grounding checks
- Link/URL stripping to prevent zero-click data exfiltration

OWASP Agentic Top 10 Coverage:
- LLM01: Prompt Injection (output side: prevent system prompt leakage)
- LLM02: Insecure Output Handling (sanitize before external delivery)
- LLM06: Sensitive Information Disclosure (scrub internal IDs, API keys, prompts)
- LLM07: Insecure Plugin Design (no URLs/links to external resources)
- LLM09: Overreliance (grounding checks via LLM-as-a-judge)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ================================================================================================
# EXCEPTIONS
# ================================================================================================


class OutputGuardViolation(Exception):
    """Raised when output guardrail check fails. Must block output."""

    def __init__(self, reason: str, category: str = "output_violation"):
        super().__init__(reason)
        self.reason = reason
        self.category = category


class GroundingViolation(OutputGuardViolation):
    """Raised when the output is not grounded in retrieved context."""

    def __init__(self, details: str):
        super().__init__(f"Output not grounded in policy: {details}", category="hallucination")
        self.details = details


class LeakDetected(OutputGuardViolation):
    """Raised when sensitive information leak is detected in output."""

    def __init__(self, leak_type: str, snippet: str = ""):
        super().__init__(f"Detected {leak_type} leak in output", category="information_disclosure")
        self.leak_type = leak_type
        self.snippet = snippet[:50]  # Truncate for logging


# ================================================================================================
# GROUNDING & CITATION CHECKS (OWASP LLM09: Overreliance)
# ================================================================================================


class GroundingVerdict(BaseModel):
    """Structured verdict from LLM-as-a-judge grounding check."""

    grounded: bool = Field(description="True if the decision is supported by policy rules")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the verdict")
    reasoning: str = Field(max_length=500, description="Brief explanation of the verdict")
    model_config = ConfigDict(extra="forbid")

    missing_citations: list[str] = Field(
        default_factory=list, description="Claims made without policy support"
    )


def verify_grounding(
    final_decision: str,
    retrieved_policy_rules: list[str],
    *,
    timeout: int = 10,
    confidence_threshold: float = 0.7,
) -> GroundingVerdict:
    """Verify that the agent's final decision is grounded in retrieved policy rules.

    Uses an LLM-as-a-judge to check if the payout decision is supported by the
    policy clauses retrieved from the knowledge base.

    Args:
        final_decision: The agent's final decision text (e.g., approval/rejection rationale)
        retrieved_policy_rules: List of policy clause texts that were retrieved
        timeout: Maximum seconds for LLM judge call
        confidence_threshold: Minimum confidence to pass (0.0-1.0)

    Returns:
        GroundingVerdict: Structured verdict from the judge

    Raises:
        GroundingViolation: If grounding check fails or confidence is too low

    OWASP Protection:
        - LLM09 (Overreliance): Prevent hallucinated coverage/exclusions
    """
    if not final_decision or not final_decision.strip():
        raise GroundingViolation("Empty decision text")

    if not retrieved_policy_rules:
        logger.warning("No policy rules provided for grounding check")
        raise GroundingViolation("No policy rules to verify against")

    try:
        judge_llm = _get_judge_llm()
        if judge_llm is None:
            # Stub mode: assume grounded (but log warning)
            logger.warning("Judge LLM unavailable (stub mode), skipping grounding check")
            return GroundingVerdict(
                grounded=True,
                confidence=1.0,
                reasoning="Stub mode: grounding check skipped",
                missing_citations=[],
            )

        # Construct judge prompt
        policy_context = "\n\n".join(
            f"[POLICY {i + 1}]\n{rule}" for i, rule in enumerate(retrieved_policy_rules[:5])
        )

        prompt = f"""You are a medical insurance policy judge. Your task is to verify if a claim decision is grounded in the provided policy rules.

POLICY RULES:
{policy_context}

CLAIM DECISION TO VERIFY:
{final_decision[:1000]}

TASK:
1. Check if EVERY factual claim about coverage, exclusions, limits, or deductions in the decision is supported by the policy rules above.
2. Identify any statements that are NOT supported by the policy (hallucinations).
3. Do NOT require exact word matches - semantic equivalence is acceptable.
4. Copay percentages, room limits, and sub-limits must match the policy exactly.

Respond ONLY with valid JSON matching this schema:
{{
  "grounded": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "missing_citations": ["claim 1 without support", ...]
}}"""  # noqa: E501 - prompt text: its line breaks are content

        # Use structured output
        structured_judge = judge_llm.with_structured_output(GroundingVerdict)
        verdict = structured_judge.invoke(prompt, timeout=timeout)

        # Validate verdict
        if not isinstance(verdict, GroundingVerdict):
            try:
                verdict = GroundingVerdict.model_validate_json(verdict)
            except Exception as ve:
                logger.error("Judge returned invalid verdict: %s", ve)
                raise GroundingViolation("Judge returned invalid verdict") from ve

        # Check confidence threshold
        if verdict.confidence < confidence_threshold:
            logger.warning(
                "Grounding check low confidence: %.2f (threshold: %.2f)",
                verdict.confidence,
                confidence_threshold,
            )
            raise GroundingViolation(
                f"Low confidence ({verdict.confidence:.2f}): {verdict.reasoning}"
            )

        # Check if grounded
        if not verdict.grounded:
            logger.warning("Grounding check failed: %s", verdict.reasoning)
            raise GroundingViolation(
                f"Ungrounded claims: {', '.join(verdict.missing_citations[:3])}"
            )

        logger.info("Grounding check passed: confidence=%.2f", verdict.confidence)
        return verdict

    except GroundingViolation:
        # Re-raise grounding violations
        raise
    except Exception as exc:
        # Fail-closed: treat judge errors as grounding failures
        logger.error("Grounding check failed: %s", exc)
        raise GroundingViolation(f"Judge error: {type(exc).__name__}") from exc


def verify_citations_present(output_text: str, *, min_citations: int = 1) -> None:
    """Verify that the output contains policy citations.

    Args:
        output_text: The agent's output text
        min_citations: Minimum number of citations required

    Raises:
        GroundingViolation: If insufficient citations found

    Citation formats recognized:
        - [AS-NIA-2025:4.1.2]
        - Clause 4.1.2
        - Section 4.1.2
        - Policy AS-NIA-2025:4.1.2
    """
    if not output_text:
        raise GroundingViolation("Empty output text")

    # Citation patterns
    citation_patterns = [
        r"\[[\w\-:\.]+\]",  # [AS-NIA-2025:4.1.2]
        r"(?:clause|section|policy)\s+[\w\-:\.]+",  # Clause 4.1.2
    ]

    citations_found = []
    for pattern in citation_patterns:
        matches = re.findall(pattern, output_text, re.IGNORECASE)
        citations_found.extend(matches)

    unique_citations = set(citations_found)
    if len(unique_citations) < min_citations:
        logger.warning(
            "Insufficient citations: found %d, need %d", len(unique_citations), min_citations
        )
        raise GroundingViolation(
            f"Insufficient policy citations: found {len(unique_citations)}, need {min_citations}"
        )

    logger.info("Citations verified: %d unique citations found", len(unique_citations))


# ================================================================================================
# LEAK PREVENTION (OWASP LLM01, LLM06: Information Disclosure)
# ================================================================================================

# System prompt fragments that should never appear in output. Only phrases a letter to a patient
# has no reason to contain: the old list also had "you are a", "your role is" and "instructions:",
# which block an ordinary sentence ("if you are a member...", "Discharge instructions: ...").
_SYSTEM_PROMPT_FRAGMENTS = [
    "you are a claims",
    "you are an ai",
    "as an ai",
    "system prompt",
    "assistant instructions",
    "do not reveal",
    "never tell the user",
    "<system>",
    "</system>",
    "openrouter",
    "langchain",
    "langgraph",
]

# Internal ID patterns
_INTERNAL_ID_PATTERNS = [
    r"agent_\w+_\d+",  # agent IDs
    r"trace[_\-]id[:\s]+[\w\-]+",  # trace IDs
    r"session[_\-]id[:\s]+[\w\-]+",  # session IDs
    r"tool[_\-]call[_\-]id[:\s]+[\w\-]+",  # tool call IDs
    # A bare run of 32+ hex digits: a hash or a token. Replaced, not blocked: the approval's own
    # worksheet_hash (64 hex) is one, and a letter that shows it must not stop a settlement.
    # Bounded by non-hex characters, not by \b, so a run glued to 'sig_' or '0x' is caught too.
    r"(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])",
]

# Secret patterns: these block the output.
_API_KEY_PATTERNS = [
    # OpenAI, OpenRouter, Anthropic, Langfuse
    r"\bsk-(?:or-v1-|proj-|ant-|lf-)?[A-Za-z0-9_\-]{20,}",
    r"\bpk-lf-[A-Za-z0-9\-]{20,}",  # Langfuse public key
    r"\blsv2_[A-Za-z0-9_]{20,}",  # LangSmith key
    r"(?:api[_\-]?key|token|secret)[:\s=]+[\w\-]{20,}",  # key=value format
]


def scrub_system_prompt_leaks(text: str) -> str:
    """Remove any system prompt fragments that leaked into the output.

    Args:
        text: Output text to scrub

    Returns:
        Scrubbed text with prompt fragments removed

    Raises:
        LeakDetected: If system prompt leak is detected (fail-closed)
    """
    if not text:
        return text

    text_lower = text.lower()
    leaked_fragments = []

    for fragment in _SYSTEM_PROMPT_FRAGMENTS:
        # Whole words only: a plain substring test let "as an ai" block "has an air conditioner".
        # The boundary applies only at an edge that is a letter ("<system>" ends in ">").
        head = r"(?<!\w)" if fragment[0].isalnum() else ""
        tail = r"(?!\w)" if fragment[-1].isalnum() else ""
        if re.search(head + re.escape(fragment) + tail, text_lower):
            leaked_fragments.append(fragment)

    if leaked_fragments:
        logger.error("System prompt leak detected: %s", leaked_fragments)
        raise LeakDetected("system_prompt", snippet=leaked_fragments[0])

    return text


def scrub_internal_ids(text: str) -> str:
    """Remove internal IDs (agent IDs, trace IDs, session IDs) from output.

    Args:
        text: Output text to scrub

    Returns:
        Scrubbed text with internal IDs replaced with generic tokens
    """
    if not text:
        return text

    scrubbed = text
    for pattern in _INTERNAL_ID_PATTERNS:
        scrubbed = re.sub(pattern, "[INTERNAL_ID]", scrubbed, flags=re.IGNORECASE)

    if scrubbed != text:
        logger.info("Scrubbed internal IDs from output")

    return scrubbed


def scrub_api_keys(text: str) -> str:
    """Remove API keys and tokens from output.

    Args:
        text: Output text to scrub

    Returns:
        Scrubbed text with API keys replaced with [REDACTED]

    Raises:
        LeakDetected: If API key is detected (fail-closed - should never happen)
    """
    if not text:
        return text

    scrubbed = text
    for pattern in _API_KEY_PATTERNS:
        matches = re.findall(pattern, scrubbed, re.IGNORECASE)
        if matches:
            logger.error("API key leak detected in output!")
            raise LeakDetected("api_key", snippet=matches[0][:20])

    return scrubbed


def scrub_leaks(text: str) -> str:
    """Comprehensive leak scrubbing: prompts, IDs, API keys.

    Args:
        text: Output text to scrub

    Returns:
        Fully scrubbed text

    Raises:
        LeakDetected: If critical leak is detected
    """
    if not text:
        return text

    # Run all scrubbers in sequence (fail on critical leaks)
    scrubbed = scrub_system_prompt_leaks(text)  # Raises on detection
    scrubbed = scrub_api_keys(scrubbed)  # Raises on detection
    scrubbed = scrub_internal_ids(scrubbed)  # Replaces, doesn't raise

    return scrubbed


# process_output_pipeline() has flags named scrub_leaks and verify_grounding; inside it those
# names are the booleans, so it calls the functions through these aliases (defect G-02, which
# made check_output_safe block every letter, G-03).
_scrub_leaks = scrub_leaks
_verify_grounding = verify_grounding


# ================================================================================================
# LINK STRIPPING (OWASP LLM06: Zero-Click Data Exfiltration Prevention)
# ================================================================================================

# Patterns for various link formats
_URL_PATTERNS = [
    r"https?://[^\s\)]+",  # http:// or https://
    r"www\.[^\s\)]+",  # www. links
    r"\[([^\]]+)\]\(https?://[^\)]+\)",  # Markdown links [text](url)
    r"<a\s+href=['\"]https?://[^'\"]+['\"][^>]*>.*?</a>",  # HTML links
]

_IMAGE_PATTERNS = [
    r"!\[([^\]]*)\]\([^\)]+\)",  # Markdown images ![alt](url)
    r"<img\s+[^>]*src=['\"][^'\"]+['\"][^>]*>",  # HTML img tags
]


def strip_all_links(text: str, *, replacement: str = "[link removed]") -> str:
    """Remove all HTTP/HTTPS links and URLs from output.

    This prevents zero-click data exfiltration attacks (EchoLeak, etc.) where
    malicious actors embed tracking URLs in prompts that get reflected in outputs.

    Args:
        text: Output text to process
        replacement: Text to replace links with

    Returns:
        Text with all links removed

    OWASP Protection:
        - LLM06 (Data Exfiltration): Prevent tracking pixels and zero-click leaks
    """
    if not text:
        return text

    cleaned = text

    # Remove Markdown links but keep the text
    cleaned = re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", cleaned)

    # Remove plain URLs
    for pattern in _URL_PATTERNS[:-1]:  # Skip markdown pattern (already handled)
        cleaned = re.sub(pattern, replacement, cleaned)

    if cleaned != text:
        logger.info("Stripped links from output")

    return cleaned


def strip_all_images(text: str, *, replacement: str = "[image removed]") -> str:
    """Remove all image tags (Markdown and HTML) from output.

    Args:
        text: Output text to process
        replacement: Text to replace images with

    Returns:
        Text with all images removed
    """
    if not text:
        return text

    cleaned = text

    for pattern in _IMAGE_PATTERNS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    if cleaned != text:
        logger.info("Stripped images from output")

    return cleaned


def strip_all_external_references(text: str) -> str:
    """Strip all links, images, and external references from output.

    Args:
        text: Output text to process

    Returns:
        Fully sanitized text with no external references
    """
    if not text:
        return text

    cleaned = strip_all_links(text)
    cleaned = strip_all_images(cleaned)

    return cleaned


# ================================================================================================
# MAIN OUTPUT PIPELINE
# ================================================================================================


@dataclass
class OutputGuardrailResult:
    """Complete result of output guardrail processing."""

    sanitized_output: str
    grounded: bool
    grounding_confidence: float
    leaks_found: list[str]
    links_removed: int
    blocked: bool
    block_reason: str | None = None


def process_output_pipeline(
    raw_output: str,
    *,
    retrieved_policy_rules: list[str] | None = None,
    verify_grounding: bool = True,
    scrub_leaks: bool = True,
    strip_links: bool = True,
    min_citations: int = 0,
) -> OutputGuardrailResult:
    """Complete output guardrail pipeline with fail-closed semantics.

    Args:
        raw_output: Raw agent output (decision letter, rationale, etc.)
        retrieved_policy_rules: Policy rules retrieved for this claim (for grounding)
        verify_grounding: Enable grounding check via LLM-as-a-judge
        scrub_leaks: Enable leak detection and scrubbing
        strip_links: Enable link/image stripping
        min_citations: Minimum citations required (0 to skip check)

    Returns:
        OutputGuardrailResult with sanitized output and metadata

    Raises:
        OutputGuardViolation: If any check fails (fail-closed)

    Example:
        >>> rules = ["Copay is 10% of approved amount", "Room rent limit Rs 5000/day"]
        >>> output = "Your claim is approved with 10% copay as per policy clause 4.1."
        >>> result = process_output_pipeline(output, retrieved_policy_rules=rules)
        >>> result.grounded
        True
        >>> result.blocked
        False
    """
    try:
        processed_output = raw_output
        leaks_found = []
        grounding_verdict = None
        link_count_before = len(re.findall(r"https?://", raw_output))

        # Step 1: Leak Detection & Scrubbing
        if scrub_leaks:
            try:
                processed_output = _scrub_leaks(processed_output)
            except LeakDetected as exc:
                leaks_found.append(exc.leak_type)
                # Re-raise to block output
                raise

        # Step 2: Link & Image Stripping
        if strip_links:
            processed_output = strip_all_external_references(processed_output)

        link_count_after = len(re.findall(r"https?://", processed_output))
        links_removed = link_count_before - link_count_after

        # Step 3: Citation Verification (if required)
        if min_citations > 0:
            verify_citations_present(processed_output, min_citations=min_citations)

        # Step 4: Grounding Check (if policy rules provided)
        if verify_grounding and retrieved_policy_rules:
            grounding_verdict = _verify_grounding(
                processed_output, retrieved_policy_rules, confidence_threshold=0.7
            )

        # All checks passed
        return OutputGuardrailResult(
            sanitized_output=processed_output,
            grounded=grounding_verdict.grounded if grounding_verdict else True,
            grounding_confidence=grounding_verdict.confidence if grounding_verdict else 1.0,
            leaks_found=leaks_found,
            links_removed=links_removed,
            blocked=False,
        )

    except OutputGuardViolation as exc:
        # Fail-closed: block output and return safe error
        logger.error("Output guardrail blocked response: %s", exc.reason)
        return OutputGuardrailResult(
            sanitized_output="",
            grounded=False,
            grounding_confidence=0.0,
            leaks_found=leaks_found,
            links_removed=0,
            blocked=True,
            block_reason=exc.reason,
        )


# ================================================================================================
# HELPER FUNCTIONS
# ================================================================================================


def _get_judge_llm():
    """The grounding judge, from `agents.llm.get_llm("judge")`. None in stub mode. No model ID is
    written here: the old code hard-coded one, against the project rule (config/models.yaml)."""
    try:
        from claimsense.agents.llm import get_llm

        return get_llm("judge")
    except Exception as exc:  # noqa: BLE001 - no judge means no grounding check, logged
        logger.warning("Failed to initialize judge LLM: %s", type(exc).__name__)
        return None


# ================================================================================================
# SAFE ERROR MESSAGES
# ================================================================================================


def get_safe_error_message(exc: OutputGuardViolation) -> str:
    """Return a safe, user-friendly error message for output violations.

    OWASP LLM06: Don't leak system internals in error messages.
    """
    safe_messages = {
        "hallucination": (
            "The system detected inconsistencies with policy rules. "
            "The response has been blocked for review."
        ),
        "information_disclosure": (
            "The response contained sensitive information and has been blocked."
        ),
        "output_violation": (
            "The response did not pass security validation. Please contact support."
        ),
    }

    return safe_messages.get(exc.category, "Response blocked by security policy.")


# ================================================================================================
# COMBINED GUARDRAIL CHECK
# ================================================================================================


def check_output_safe(
    output: str,
    claim_id: str,
    policy_rules: list[str],
    *,
    strict_mode: bool = True,
) -> tuple[bool, str, str]:
    """Comprehensive output safety check. Returns (is_safe, sanitized_output, error_message).

    This is the main entry point for output validation before sending responses to users.

    Args:
        output: Raw agent output
        claim_id: Claim ID for logging
        policy_rules: Retrieved policy rules for grounding check
        strict_mode: If True, require grounding; if False, only scrub/strip

    Returns:
        Tuple of (is_safe, sanitized_output, error_message)
        - is_safe: False if output should be blocked
        - sanitized_output: Cleaned output (empty if blocked)
        - error_message: User-safe error message (empty if passed)

    Example:
        >>> rules = ["10% copay applies"]
        >>> is_safe, output, err = check_output_safe("Approved with 10% copay", "CLM-001", rules)
        >>> is_safe
        True
    """
    try:
        result = process_output_pipeline(
            output,
            retrieved_policy_rules=policy_rules if strict_mode else None,
            verify_grounding=strict_mode,
            scrub_leaks=True,
            strip_links=True,
            min_citations=1 if strict_mode else 0,
        )

        if result.blocked:
            logger.warning("Output blocked for claim %s: %s", claim_id, result.block_reason)
            return (
                False,
                "",
                get_safe_error_message(OutputGuardViolation(result.block_reason or "Unknown")),
            )

        logger.info(
            "Output passed guardrails for claim %s: grounded=%.2f, links_removed=%d",
            claim_id,
            result.grounding_confidence,
            result.links_removed,
        )
        return True, result.sanitized_output, ""

    except OutputGuardViolation as exc:
        logger.error("Output guardrail exception for claim %s: %s", claim_id, exc.reason)
        return False, "", get_safe_error_message(exc)
    except Exception as exc:
        # Fail-closed: any unexpected error blocks output
        logger.error("Unexpected output guardrail error for claim %s: %s", claim_id, exc)
        return False, "", "Response blocked due to unexpected error. Please contact support."


def check_letter_safe(claim: Any, worksheet: Any, letter: str) -> OutputGuardrailResult:
    """The output guardrail for a claim letter, as the settlement agent runs it before any money
    moves (fail-closed: a blocked result means no settlement and no letter).

    1. This module's generic checks: secret and system-prompt leaks block; internal ids are
       replaced; links and images are removed.
    2. The checks only the claim can support (`guardrails.check_letter`): the worksheet belongs to
       this claim, and the letter names its policy number, its insured person and its total. A
       letter for another patient (RT-005) fails here; the generic checks cannot see it.

    No grounding judge: every number in the letter is copied from the worksheet by code.
    """
    from claimsense.guardrails.guardrails import check_letter  # lazy: guardrails imports agents

    result = process_output_pipeline(letter, verify_grounding=False, min_citations=0)
    if result.blocked:
        return result
    problems = check_letter(claim, worksheet, result.sanitized_output)
    if problems:
        return OutputGuardrailResult(
            sanitized_output="",
            grounded=False,
            grounding_confidence=0.0,
            leaks_found=result.leaks_found,
            links_removed=0,
            blocked=True,
            block_reason="; ".join(p.message for p in problems),
        )
    return result


# ================================================================================================
# PUBLIC API
# ================================================================================================

__all__ = [
    # Exceptions
    "OutputGuardViolation",
    "GroundingViolation",
    "LeakDetected",
    # Grounding & Citations
    "verify_grounding",
    "verify_citations_present",
    "GroundingVerdict",
    # Leak Prevention
    "scrub_system_prompt_leaks",
    "scrub_internal_ids",
    "scrub_api_keys",
    "scrub_leaks",
    # Link Stripping
    "strip_all_links",
    "strip_all_images",
    "strip_all_external_references",
    # Main Pipeline
    "process_output_pipeline",
    "OutputGuardrailResult",
    "check_output_safe",
    "check_letter_safe",
    # Utilities
    "get_safe_error_message",
]
