from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from app.config import COMPETITOR_KEYWORDS


PAIN_TERMS = {
    "pain",
    "problem",
    "struggle",
    "struggling",
    "frustrated",
    "frustrating",
    "difficult",
    "hard",
    "issue",
    "stuck",
    "confusing",
    "messy",
    "limiting",
}

OBJECTION_TERMS = {
    "too expensive",
    "too limiting",
    "doesn't work",
    "does not work",
    "hard to justify",
    "not worth",
    "time-consuming",
    "time consuming",
    "too slow",
}

QUESTION_PREFIXES = (
    "what ",
    "why ",
    "how ",
    "which ",
    "where ",
    "when ",
    "who ",
    "is ",
    "are ",
    "can ",
    "should ",
)

STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "with",
    "this",
    "from",
    "have",
    "keep",
    "into",
    "your",
    "their",
    "about",
    "would",
    "people",
    "really",
    "using",
    "need",
    "better",
    "tool",
    "tools",
}

GROUP_NAMES = (
    "topic_candidates",
    "pain_points",
    "questions_people_ask",
    "objections",
    "competitor_mentions",
    "language_patterns",
    "content_opportunities",
)


def build_insight_groups(posts: list[dict]) -> dict[str, list[dict]]:
    groups = {name: [] for name in GROUP_NAMES}
    evidence = _build_evidence(posts)

    pain = [item for item in evidence if _contains_term(item["text"], PAIN_TERMS)]
    question = [item for item in evidence if _is_question(item["text"])]
    objection = [item for item in evidence if _contains_phrase(item["text"], OBJECTION_TERMS)]
    competitor = [item for item in evidence if _is_competitor_evidence(item)]

    repeated_phrases = _extract_repeated_phrases(evidence)
    language = []
    for phrase, count in repeated_phrases[:5]:
        phrase_evidence = [item for item in evidence if phrase in item["text"].lower()]
        language.append(
            _build_insight(
                insight_type="language_pattern",
                title=f"Repeated audience phrase: {phrase}",
                summary=f"The phrase '{phrase}' appears repeatedly across the captured Reddit discussions.",
                evidence_items=phrase_evidence,
                sample_quotes=[item["quote"] for item in phrase_evidence[:3]],
                priority=min(5, count),
                confidence=0.5 + min(0.4, count * 0.1),
            )
        )

    if pain:
        groups["pain_points"].append(
            _build_insight(
                insight_type="pain_point",
                title="Recurring audience pain points",
                summary="Users repeatedly describe friction, frustration, or difficulty around the topic.",
                evidence_items=pain,
                sample_quotes=[item["quote"] for item in pain[:3]],
                priority=min(5, len(pain)),
                confidence=0.55 + min(0.35, len(pain) * 0.08),
            )
        )
    if question:
        groups["questions_people_ask"].append(
            _build_insight(
                insight_type="question",
                title="Questions people are actively asking",
                summary="The collected discussions contain direct audience questions that can be turned into content briefs.",
                evidence_items=question,
                sample_quotes=[item["quote"] for item in question[:3]],
                priority=min(5, len(question)),
                confidence=0.6 + min(0.3, len(question) * 0.08),
            )
        )
    if objection:
        groups["objections"].append(
            _build_insight(
                insight_type="objection",
                title="Common objections and blockers",
                summary="The dataset shows recurring objections that may need objection-handling content.",
                evidence_items=objection,
                sample_quotes=[item["quote"] for item in objection[:3]],
                priority=min(5, len(objection)),
                confidence=0.55 + min(0.35, len(objection) * 0.08),
            )
        )
    if competitor:
        groups["competitor_mentions"].append(
            _build_insight(
                insight_type="competitor_mention",
                title="Competitor and alternative mentions",
                summary="People are explicitly naming competitor tools or alternatives in the thread.",
                evidence_items=competitor,
                sample_quotes=[item["quote"] for item in competitor[:3]],
                priority=min(5, len(competitor)),
                confidence=0.65 + min(0.25, len(competitor) * 0.05),
            )
        )

    groups["language_patterns"] = language

    topic_candidates = []
    if groups["questions_people_ask"]:
        topic_candidates.append(
            _build_rollup_insight(
                insight_type="topic_candidate",
                title="Topic candidate: answer the recurring Reddit questions",
                summary="Questions and blockers in these threads can be turned into topical educational or comparison content.",
                source_groups=[groups["questions_people_ask"][0], *groups["pain_points"][:1]],
                priority=4,
                confidence=0.72,
            )
        )
    groups["topic_candidates"] = topic_candidates

    content_opportunities = []
    if groups["pain_points"] or groups["questions_people_ask"] or groups["competitor_mentions"]:
        content_opportunities.append(
            _build_rollup_insight(
                insight_type="content_opportunity",
                title="Content opportunity: convert Reddit pain into planner-ready briefs",
                summary="The combination of repeated questions, pain points, and competitor references suggests clear material for weekly plans.",
                source_groups=[
                    *groups["pain_points"][:1],
                    *groups["questions_people_ask"][:1],
                    *groups["competitor_mentions"][:1],
                ],
                priority=5,
                confidence=0.78,
            )
        )
    groups["content_opportunities"] = content_opportunities
    return groups


def flatten_insights(groups: dict[str, list[dict]], insight_type: str | None = None) -> list[dict]:
    items: list[dict] = []
    for group_items in groups.values():
        for item in group_items:
            if insight_type and item["type"] != insight_type:
                continue
            items.append(item)
    return sorted(items, key=lambda item: (-int(item["priority"]), -float(item["confidence"]), item["insight_id"]))


def _build_evidence(posts: list[dict]) -> list[dict]:
    items: list[dict] = []
    for post in posts:
        post_text = " ".join(part for part in [post.get("title"), post.get("body_text") or post.get("body")] if part)
        items.append(
            {
                "kind": "post",
                "text": post_text,
                "quote": post.get("title") or post.get("body_text") or "",
                "post_id": post["reddit_post_id"],
                "comment_id": None,
                "subreddit": post.get("subreddit"),
                "created_at": int(post.get("created_utc", post.get("created_at", 0)) or 0),
                "competitor_hint": bool(post.get("competitor_mentioned_in_thread")),
            }
        )
        for comment in post.get("comments", []):
            items.append(
                {
                    "kind": "comment",
                    "text": str(comment.get("body_text") or comment.get("body") or ""),
                    "quote": str(comment.get("body_text") or comment.get("body") or ""),
                    "post_id": post["reddit_post_id"],
                    "comment_id": comment.get("reddit_comment_id"),
                    "subreddit": post.get("subreddit"),
                    "created_at": int(comment.get("created_utc", comment.get("created_at", 0)) or 0),
                    "competitor_hint": False,
                }
            )
    return items


def _build_insight(
    *,
    insight_type: str,
    title: str,
    summary: str,
    evidence_items: list[dict],
    sample_quotes: list[str],
    priority: int,
    confidence: float,
) -> dict:
    created_values = [item["created_at"] for item in evidence_items if item.get("created_at") is not None]
    source_post_ids = sorted({str(item["post_id"]) for item in evidence_items if item.get("post_id")})
    source_comment_ids = sorted({str(item["comment_id"]) for item in evidence_items if item.get("comment_id")})
    subreddits = sorted({str(item["subreddit"]) for item in evidence_items if item.get("subreddit")})
    first_seen = min(created_values) if created_values else None
    last_seen = max(created_values) if created_values else None
    insight_id = f"{insight_type}:{'-'.join(source_post_ids[:2] or ['none'])}:{len(source_comment_ids)}"
    return {
        "insight_id": insight_id,
        "type": insight_type,
        "title": title,
        "summary": summary,
        "evidence_count": len(evidence_items),
        "sample_quotes": [quote for quote in sample_quotes if quote][:3],
        "source_post_ids": source_post_ids,
        "source_comment_ids": source_comment_ids,
        "subreddits": subreddits,
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "priority": max(1, min(5, priority)),
    }


def _build_rollup_insight(
    *,
    insight_type: str,
    title: str,
    summary: str,
    source_groups: list[dict],
    priority: int,
    confidence: float,
) -> dict:
    evidence_items = []
    for item in source_groups:
        evidence_items.extend(
            {
                "post_id": post_id,
                "comment_id": None,
                "subreddit": subreddit,
                "created_at": item["first_seen_at"] or 0,
            }
            for post_id in item.get("source_post_ids", [])
            for subreddit in item.get("subreddits", []) or [None]
        )
    sample_quotes = []
    for item in source_groups:
        sample_quotes.extend(item.get("sample_quotes", []))
    return _build_insight(
        insight_type=insight_type,
        title=title,
        summary=summary,
        evidence_items=evidence_items,
        sample_quotes=sample_quotes,
        priority=priority,
        confidence=confidence,
    )


def _contains_term(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _contains_phrase(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _is_question(text: str) -> bool:
    lowered = text.strip().lower()
    return "?" in text or lowered.startswith(QUESTION_PREFIXES)


def _is_competitor_evidence(item: dict) -> bool:
    lowered = item["text"].lower()
    return bool(item.get("competitor_hint")) or any(keyword in lowered for keyword in COMPETITOR_KEYWORDS)


def _extract_repeated_phrases(evidence: list[dict]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for item in evidence:
        tokens = [
            token
            for token in re.findall(r"[a-z0-9']+", item["text"].lower())
            if len(token) >= 4 and token not in STOPWORDS
        ]
        counter.update(tokens)
    return sorted(
        [(phrase, count) for phrase, count in counter.items() if count >= 2],
        key=lambda item: (-item[1], item[0]),
    )
