"""Heuristics for keeping the local graph and simulation cast concrete.

The local fast extraction path intentionally avoids an extra LLM pass, so we need
cheap guardrails that reject obvious metadata, feed labels, dates, and headline
fragments before they become simulated actors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Sequence

GENERIC_SINGLE_TOKEN_BLACKLIST = {
    "additional", "analysis", "api", "best", "configured", "deadline", "end",
    "evidence", "generated", "how", "keyword", "latest", "liquidity", "market",
    "news", "official", "plan", "primary", "questions", "recent", "reference",
    "region", "relevant", "resolution", "risk", "rss", "seed", "source",
    "suggested", "the", "this", "top", "tracked", "trend", "url", "use", "utc",
    "what", "which", "why", "yes", "ddg", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "january", "february", "headline",
    "trade", "buy", "sell", "observed", "current", "regional", "ignore",
    "focus", "model", "collection", "operations", "down", "up",
}

GENERIC_PHRASE_BLACKLIST = {
    "google news",
    "seed packet",
    "pm et",
    "polymarket gamma",
}

HEADLINE_FRAGMENT_TOKENS = {
    "is", "are", "was", "were", "be", "being", "been", "raises", "raise",
    "rising", "outlasts", "sent", "sending", "incentivizing", "incentive",
    "warns", "warning", "says", "said", "asks", "asking", "should", "would",
    "could", "will", "may", "might", "with", "without", "into", "toward",
    "towards", "after", "before", "during", "because", "amid", "amidst",
}

TIME_AND_CLOCK_TOKENS = {
    "utc", "gmt", "am", "pm", "et", "cet", "cest", "pst", "est",
}

ACRONYM_ALLOWLIST = {
    "iaea", "irgc", "jcpoa", "idf", "nato", "eu", "un", "uk", "uae", "usd",
    "btc", "eth",
}

CONCRETE_SINGLE_TOKEN_ALLOWLIST = {
    "iran", "israel", "trump", "tehran", "gaza", "hamas", "hezbollah", "syria",
    "lebanon", "qatar", "egypt", "china", "russia", "saudi", "polymarket",
    "houthis", "pakistan", "iraq", "yemen",
}

CONCRETE_MULTIWORD_ALLOWLIST = {
    "united states",
    "arabian sea",
    "persian gulf",
    "red sea",
    "eastern mediterranean sea",
    "the new york times",
    "al jazeera",
    "modern diplomacy",
    "iran international",
}

ROLE_OVERRIDES = {
    "trump": "publicfigure",
    "donald trump": "publicfigure",
    "the new york times": "mediaoutlet",
    "al jazeera": "mediaoutlet",
    "modern diplomacy": "mediaoutlet",
    "iran international": "mediaoutlet",
    "small wars journal": "mediaoutlet",
    "just security": "mediaoutlet",
    "cato institute": "organization",
    "polymarket": "company",
    "houthis": "group",
    "hamas": "group",
    "hezbollah": "group",
    "iaea": "organization",
    "irgc": "organization",
}

COUNTRY_NAMES = {
    "iran", "israel", "united states", "pakistan", "north korea", "china",
    "russia", "egypt", "qatar", "iraq", "yemen", "syria", "lebanon",
}

SIGNAL_SUFFIXES = {
    "sea", "gulf", "states", "times", "international", "ministry", "department",
}

LABEL_BOOSTS = {
    "publicfigure", "organization", "governmentagency", "mediaoutlet",
    "company", "institution", "country", "location",
}

ROLE_WEIGHTS = {
    "nationstate": 2.2,
    "group": 2.0,
    "organization": 1.8,
    "governmentagency": 1.8,
    "institution": 1.6,
    "mediaoutlet": 1.3,
    "publicfigure": 1.4,
    "company": 1.1,
    "location": 1.0,
    "country": 2.0,
}

GENERIC_ROLE_TYPES = {"entity", "unknown", "node"}
TEMPORAL_FRAGMENT_TOKENS = {
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "sept",
    "september", "oct", "october", "nov", "november", "dec", "december",
    "q1", "q2", "q3", "q4",
}


@dataclass(frozen=True)
class EntityQualityDecision:
    keep: bool
    score: float
    reason: str


@dataclass(frozen=True)
class EntityAdmissionDecision:
    keep: bool
    score: float
    threshold: float
    role: str
    reason: str
    rationale: str
    breakdown: dict[str, float] = field(default_factory=dict)


def normalize_entity_key(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]+", " ", str(value or "").lower())).strip()


def entity_tokens(value: str) -> list[str]:
    return [token for token in normalize_entity_key(value).split() if token]


def _is_temporal_fragment_token(token: str) -> bool:
    normalized = normalize_entity_key(token)
    if not normalized:
        return False
    if normalized in TEMPORAL_FRAGMENT_TOKENS:
        return True
    if re.fullmatch(r"(19|20)\d{2}", normalized):
        return True
    if re.fullmatch(r"\d{1,2}(st|nd|rd|th)?", normalized):
        return True
    return False


def selection_entity_key(value: str) -> str:
    tokens = [token for token in entity_tokens(value) if not _is_temporal_fragment_token(token)]
    if tokens:
        return " ".join(tokens)
    return normalize_entity_key(value)


def selection_preference_score(name: str, role: str, score: float, graph_degree: int = 0) -> float:
    role_norm = normalize_entity_key(role)
    preference = float(score)
    if role_norm and role_norm not in GENERIC_ROLE_TYPES:
        preference += 2.5
    if role_norm in ROLE_WEIGHTS:
        preference += 0.75
    if any(_is_temporal_fragment_token(token) for token in entity_tokens(name)):
        preference -= 4.0
    preference += min(max(graph_degree, 0), 6) * 0.15
    return round(preference, 2)


def _looks_like_numeric_or_clock(text: str) -> bool:
    compact = text.replace(" ", "")
    if re.fullmatch(r"\d+([:/-]\d+)*", compact):
        return True
    if re.fullmatch(r"\d{1,2}(am|pm)", compact):
        return True
    return False


def build_anchor_terms(anchor_terms: Sequence[str] | None = None, anchor_text: str = "") -> set[str]:
    terms: set[str] = set()
    for raw in anchor_terms or []:
        normalized = normalize_entity_key(raw)
        if not normalized:
            continue
        for token in normalized.split():
            if len(token) >= 3 and token not in GENERIC_SINGLE_TOKEN_BLACKLIST and token not in HEADLINE_FRAGMENT_TOKENS:
                terms.add(token)
        terms.add(normalized)
    for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", normalize_entity_key(anchor_text)):
        if token in GENERIC_SINGLE_TOKEN_BLACKLIST or token in HEADLINE_FRAGMENT_TOKENS:
            continue
        terms.add(token)
    return terms


def _count_term_hits(text: str, terms: Sequence[str]) -> int:
    normalized = normalize_entity_key(text)
    if not normalized:
        return 0
    hits = 0
    for term in terms:
        normalized_term = normalize_entity_key(term)
        if not normalized_term:
            continue
        if normalized_term in normalized:
            hits += 1
    return hits


def _related_anchor_hits(related_names: Sequence[str] | None, anchor_terms: set[str]) -> int:
    hits = 0
    for name in related_names or []:
        normalized = normalize_entity_key(name)
        if not normalized:
            continue
        if normalized in anchor_terms:
            hits += 1
            continue
        tokens = entity_tokens(normalized)
        if any(token in anchor_terms for token in tokens):
            hits += 1
    return hits


def assess_entity_candidate(
    name: str,
    *,
    summary: str = "",
    labels: Sequence[str] | None = None,
    anchor_terms: Sequence[str] | None = None,
    anchor_text: str = "",
) -> EntityQualityDecision:
    normalized = normalize_entity_key(name)
    if not normalized:
        return EntityQualityDecision(False, -10.0, "empty")

    if normalized in GENERIC_PHRASE_BLACKLIST:
        return EntityQualityDecision(False, -9.0, "blacklisted_phrase")

    if _looks_like_numeric_or_clock(normalized):
        return EntityQualityDecision(False, -8.0, "numeric_or_clock")

    tokens = entity_tokens(name)
    if not tokens:
        return EntityQualityDecision(False, -10.0, "empty")

    contextual_terms = build_anchor_terms(anchor_terms, anchor_text)
    contextual_hits = 0
    if contextual_terms:
        normalized_summary = normalize_entity_key(summary)
        contextual_hits += sum(1 for token in tokens if token in contextual_terms)
        if normalized in contextual_terms:
            contextual_hits += 2
        if normalized_summary:
            contextual_hits += sum(1 for token in contextual_terms if token in normalized_summary)

    if any(token in TIME_AND_CLOCK_TOKENS for token in tokens):
        return EntityQualityDecision(False, -7.0, "time_token")

    if len(tokens) >= 3 and any(token in HEADLINE_FRAGMENT_TOKENS for token in tokens):
        return EntityQualityDecision(False, -6.0, "headline_fragment")

    if len(tokens) == 1:
        token = tokens[0]
        if token in GENERIC_SINGLE_TOKEN_BLACKLIST and contextual_hits == 0:
            return EntityQualityDecision(False, -7.0, "generic_single_token")
        if len(token) <= 3 and token not in ACRONYM_ALLOWLIST:
            return EntityQualityDecision(False, -6.0, "short_token")
        if token in CONCRETE_SINGLE_TOKEN_ALLOWLIST:
            return EntityQualityDecision(True, 8.0, "allowlisted_single_token")
        if token in ACRONYM_ALLOWLIST:
            return EntityQualityDecision(True, 7.0, "allowlisted_acronym")
        if contextual_hits >= 2:
            return EntityQualityDecision(True, 6.5, "contextual_single_token")
        return EntityQualityDecision(False, -4.0, "single_token_not_allowlisted")

    if normalized in CONCRETE_MULTIWORD_ALLOWLIST:
        return EntityQualityDecision(True, 8.5, "allowlisted_multiword")

    if any(token in GENERIC_SINGLE_TOKEN_BLACKLIST or token in HEADLINE_FRAGMENT_TOKENS for token in tokens):
        return EntityQualityDecision(False, -5.5, "generic_phrase_token")
    if tokens[0] in {"the", "a", "an"} and len(tokens) < 3:
        return EntityQualityDecision(False, -4.5, "leading_article_fragment")
    if len(tokens) > 4:
        return EntityQualityDecision(False, -4.5, "too_many_tokens")

    score = 0.0
    if len(tokens) >= 2:
        score += 3.0
    else:
        score += 1.0

    if len(tokens) <= 4:
        score += 1.0
    else:
        score -= 2.0

    if any(token in SIGNAL_SUFFIXES for token in tokens):
        score += 1.5

    if labels:
        label_tokens = {normalize_entity_key(label) for label in labels if label}
        score += 1.5 * len(label_tokens & LABEL_BOOSTS)
    else:
        label_tokens = set()

    lowered_summary = normalize_entity_key(summary)
    if lowered_summary and "extracted from source text mentioning" not in lowered_summary:
        score += 1.0

    if contextual_terms:
        score += contextual_hits * 1.75
        if contextual_hits == 0 and not (label_tokens & LABEL_BOOSTS) and normalized not in COUNTRY_NAMES:
            score -= 4.0

    if normalized.startswith(("this ", "what ", "why ", "how ")):
        return EntityQualityDecision(False, -6.0, "question_fragment")

    if normalized.endswith((" raises", " update", " analysis")):
        return EntityQualityDecision(False, -5.5, "headline_tail")

    if score < 3.0:
        return EntityQualityDecision(False, score, "low_signal")

    return EntityQualityDecision(True, score, "scored")


def weighted_entity_admission(
    name: str,
    *,
    summary: str = "",
    labels: Sequence[str] | None = None,
    anchor_terms: Sequence[str] | None = None,
    anchor_text: str = "",
    corpus_text: str = "",
    graph_degree: int = 0,
    related_names: Sequence[str] | None = None,
) -> EntityAdmissionDecision:
    quality = assess_entity_candidate(
        name,
        summary=summary,
        labels=labels,
        anchor_terms=anchor_terms,
        anchor_text=anchor_text,
    )
    role = infer_entity_role(name, next(iter(labels or []), ""))
    role_norm = normalize_entity_key(role)
    if not quality.keep:
        return EntityAdmissionDecision(
            keep=False,
            score=round(quality.score, 2),
            threshold=6.0,
            role=role,
            reason=quality.reason,
            rationale=f"Rejected during hygiene gate ({quality.reason}).",
            breakdown={"quality_gate": round(quality.score, 2)},
        )

    anchor_set = build_anchor_terms(anchor_terms, anchor_text)
    normalized_name = normalize_entity_key(name)
    normalized_anchor = normalize_entity_key(anchor_text)
    normalized_summary = normalize_entity_key(summary)
    normalized_corpus = normalize_entity_key(corpus_text)
    tokens = entity_tokens(name)
    label_tokens = {normalize_entity_key(label) for label in labels or [] if label}
    temporal_fragments = sum(1 for token in tokens if _is_temporal_fragment_token(token))
    generic_role = role_norm in GENERIC_ROLE_TYPES

    exact_anchor = 1.0 if normalized_name and (normalized_name in anchor_set or normalized_name in normalized_anchor) else 0.0
    token_overlap = len({token for token in tokens if token in anchor_set})
    summary_overlap = _count_term_hits(summary, sorted(anchor_set))
    corpus_mentions = normalized_corpus.count(normalized_name) if normalized_name else 0
    related_hits = _related_anchor_hits(related_names, anchor_set)
    label_hits = len(label_tokens & LABEL_BOOSTS)

    breakdown = {
        "quality_gate": round(quality.score * 1.2, 2),
        "role_signal": round(ROLE_WEIGHTS.get(role, 0.8), 2),
        "exact_anchor": round(exact_anchor * 4.0, 2),
        "token_overlap": round(token_overlap * 2.3, 2),
        "summary_overlap": round(min(summary_overlap, 5) * 1.1, 2),
        "corpus_support": round(min(corpus_mentions, 4) * 0.7, 2),
        "graph_support": round(min(max(graph_degree, 0), 10) * 0.3, 2),
        "related_support": round(min(related_hits, 4) * 0.8, 2),
        "label_support": round(label_hits * 0.8, 2),
        "generic_role_penalty": -3.0 if generic_role else 0.0,
        "temporal_fragment_penalty": -4.0 if generic_role and temporal_fragments else 0.0,
    }

    penalties = 0.0
    if exact_anchor == 0 and token_overlap == 0 and summary_overlap == 0:
        penalties += 4.5
    if corpus_mentions == 0:
        penalties += 0.6
    if len(tokens) == 1 and token_overlap == 0 and exact_anchor == 0:
        penalties += 0.8
    if role in {"mediaoutlet", "location"} and token_overlap == 0 and summary_overlap == 0:
        penalties += 1.0
    if generic_role and exact_anchor == 0 and token_overlap == 0:
        penalties += 1.5
    breakdown["penalties"] = round(-penalties, 2)

    score = sum(breakdown.values())
    threshold = 6.0
    if generic_role:
        threshold += 2.5
    if exact_anchor == 0 and token_overlap == 0:
        threshold += 1.5
    if generic_role and exact_anchor == 0 and token_overlap == 0:
        threshold += 1.5
    if len(tokens) == 1 and exact_anchor == 0:
        threshold += 0.5
    keep = score >= threshold

    if keep:
        rationale = (
            f"Admitted as {role}: anchor hits={int(exact_anchor) + token_overlap}, "
            f"summary hits={summary_overlap}, graph degree={graph_degree}."
        )
        reason = "weighted_admission"
    else:
        rationale = (
            f"Rejected as low-utility {role}: anchor hits={int(exact_anchor) + token_overlap}, "
            f"summary hits={summary_overlap}, graph degree={graph_degree}, penalties={penalties:.1f}."
        )
        reason = "below_threshold"

    return EntityAdmissionDecision(
        keep=keep,
        score=round(score, 2),
        threshold=round(threshold, 2),
        role=role,
        reason=reason,
        rationale=rationale,
        breakdown=breakdown,
    )


def infer_entity_role(name: str, current_type: str = "") -> str:
    normalized = normalize_entity_key(name)
    current = normalize_entity_key(current_type)
    if not normalized:
        return current_type or "Entity"

    if normalized in ROLE_OVERRIDES:
        return ROLE_OVERRIDES[normalized]
    if normalized in COUNTRY_NAMES:
        return "nationstate"
    if normalized.endswith((" institute", " ministry", " department", " agency")):
        return "organization"
    if normalized.endswith((" news", " times", " journal")):
        return "mediaoutlet"
    if normalized.endswith((" sea", " gulf")):
        return "location"
    if current and current not in {"person", "entity", "node"}:
        return current_type
    return current_type or "Entity"
