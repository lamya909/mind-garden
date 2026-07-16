from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from flask import current_app

from app.utils.text_processing import simple_tokenize

STOPWORDS = {
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "to",
    "of",
    "in",
    "for",
    "on",
    "at",
    "is",
    "am",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "that",
    "this",
    "with",
    "as",
    "by",
    "from",
    "about",
}

_emotion_classifier = None
_risk_classifier = None
_embedder = None
_keybert_model = None
_load_errors: dict[str, str] = {}


def _clean_for_nlp(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    tokens = [token for token in text.split() if token not in STOPWORDS]
    return " ".join(tokens)


def _load_models() -> None:
    global _emotion_classifier, _risk_classifier, _embedder, _keybert_model

    if _emotion_classifier is None and "emotion_classifier" not in _load_errors:
        try:
            from transformers import pipeline

            model_name = current_app.config["HF_EMOTION_MODEL"]
            _emotion_classifier = pipeline("text-classification", model=model_name, top_k=None)
        except Exception as exc:  # pragma: no cover
            _load_errors["emotion_classifier"] = str(exc)

    use_hf_risk_model = bool(current_app.config.get("USE_HF_RISK_MODEL", False))
    if use_hf_risk_model and _risk_classifier is None and "risk_classifier" not in _load_errors:
        try:
            from transformers import pipeline

            risk_model = current_app.config["HF_RISK_MODEL"]
            _risk_classifier = pipeline("zero-shot-classification", model=risk_model)
        except BaseException as exc:  # pragma: no cover
            _load_errors["risk_classifier"] = str(exc)

    if _embedder is None and "embedder" not in _load_errors:
        try:
            from sentence_transformers import SentenceTransformer

            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as exc:  # pragma: no cover
            _load_errors["embedder"] = str(exc)

    if _keybert_model is None and "keybert" not in _load_errors:
        try:
            from keybert import KeyBERT

            _keybert_model = KeyBERT()
        except Exception as exc:  # pragma: no cover
            _load_errors["keybert"] = str(exc)


def _fallback_emotions(cleaned: str) -> list[dict[str, float | str]]:
    buckets = {
        "joy": ["happy", "grateful", "good", "great", "excited", "calm"],
        "sadness": ["sad", "tired", "lonely", "down"],
        "anger": ["angry", "frustrated", "annoyed", "mad"],
        "fear": ["anxious", "worried", "nervous", "scared"],
        "stress": ["stress", "pressure", "deadline", "overwhelmed"],
    }
    scores = []
    for label, words in buckets.items():
        score = 0.1 + sum(0.2 for word in words if word in cleaned)
        if score > 0.15:
            scores.append({"label": label, "score": min(score, 0.95)})

    if not scores:
        scores.append({"label": "neutral", "score": 0.55})

    return sorted(scores, key=lambda item: item["score"], reverse=True)[:5]


def _extract_keywords(cleaned: str) -> list[str]:
    if _keybert_model is not None:
        extracted = _keybert_model.extract_keywords(
            cleaned,
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=5,
        )
        return [item[0] for item in extracted]

    tokens = [token for token in simple_tokenize(cleaned) if token not in STOPWORDS and len(token) > 2]
    counter = Counter(tokens)
    return [word for word, _ in counter.most_common(5)]


def _extract_explainability(cleaned: str, top_emotion: str, keywords: list[str]) -> dict[str, Any]:
    """Build a compact explanation of influential phrases behind the prediction."""
    phrases: list[str] = []
    lowered = cleaned.lower()

    emotion_cues = {
        "joy": ["happy", "grateful", "good", "great", "relaxed", "proud"],
        "stress": ["deadline", "pressure", "overwhelmed", "workload", "exam"],
        "anxiety": ["anxious", "worried", "nervous", "overthinking", "uncertain"],
        "sadness": ["sad", "low", "lonely", "drained", "tired"],
        "fear": ["scared", "afraid", "worry", "panic"],
        "anger": ["angry", "frustrated", "annoyed", "mad"],
        "neutral": ["normal", "routine", "average", "okay"],
    }

    for cue in emotion_cues.get(top_emotion, []):
        if cue in lowered:
            phrases.append(cue)

    for key in keywords:
        key_l = key.lower().strip()
        if key_l and key_l in lowered and key_l not in phrases:
            phrases.append(key_l)

    phrases = phrases[:6]
    explanation_text = (
        f"Detected {top_emotion} because the text contains signals like: {', '.join(phrases)}"
        if phrases
        else f"Detected {top_emotion} based on overall language pattern and tone."
    )
    return {"phrases": phrases, "summary": explanation_text}


def _analyze_risk(cleaned: str, keywords: list[str]) -> dict[str, Any]:
    """Separate high-risk detector independent from emotion classifier."""
    candidate_labels = [
        "high mental health risk",
        "moderate psychological distress",
        "low emotional risk",
    ]

    if _risk_classifier is not None:
        try:
            result = _risk_classifier(cleaned, candidate_labels, multi_label=False)
            labels = result.get("labels", [])
            scores = result.get("scores", [])
            if labels and scores:
                top_label = str(labels[0]).lower()
                top_score = float(scores[0])
                if "high" in top_label:
                    level = "high"
                elif "moderate" in top_label:
                    level = "moderate"
                else:
                    level = "low"
                return {
                    "level": level,
                    "score": round(top_score, 4),
                    "model": "risk_classifier",
                }
        except Exception:
            pass

    risk_terms = {
        "high": ["self-harm", "hopeless", "worthless", "can't continue", "suicide"],
        "moderate": ["burnout", "panic", "anxious", "overwhelmed", "depressed"],
    }
    joined = f"{cleaned} {' '.join(keywords)}".lower()
    if any(term in joined for term in risk_terms["high"]):
        return {"level": "high", "score": 0.9, "model": "risk_fallback"}
    if any(term in joined for term in risk_terms["moderate"]):
        return {"level": "moderate", "score": 0.75, "model": "risk_fallback"}
    return {"level": "low", "score": 0.55, "model": "risk_fallback"}


def _create_embedding(cleaned: str) -> list[float]:
    if _embedder is not None:
        vector = _embedder.encode(cleaned)
        return [float(round(value, 6)) for value in vector.tolist()]

    tokens = simple_tokenize(cleaned)
    dims = [0.0] * 32
    for index, token in enumerate(tokens[:128]):
        dims[index % 32] += (sum(ord(ch) for ch in token) % 97) / 100.0
    norm = max(sum(abs(x) for x in dims), 1.0)
    return [round(value / norm, 6) for value in dims]


def analyze_post(text: str) -> dict[str, Any]:
    """Run context-aware NLP: cleaning, multi-emotion, keyword extraction, embeddings."""
    cleaned = _clean_for_nlp(text)
    _load_models()

    if _emotion_classifier is not None:
        raw = _emotion_classifier(cleaned)[0]
        emotions = sorted(
            [
                {"label": str(item.get("label", "neutral")).lower(), "score": float(item.get("score", 0.0))}
                for item in raw
            ],
            key=lambda item: item["score"],
            reverse=True,
        )[:5]
    else:
        emotions = _fallback_emotions(cleaned)

    keywords = _extract_keywords(cleaned)
    embedding = _create_embedding(cleaned)
    top_emotion = emotions[0]["label"] if emotions else "neutral"
    explainability = _extract_explainability(cleaned, top_emotion, keywords)
    risk = _analyze_risk(cleaned, keywords)

    return {
        "cleaned_text": cleaned,
        "keywords": keywords,
        "embedding": embedding,
        "emotions": emotions,
        "top_emotion": top_emotion,
        "top_confidence": emotions[0]["score"] if emotions else 0.0,
        "explainability": explainability,
        "risk": risk,
        "load_errors": _load_errors,
    }


def to_embedding_json(vector: list[float]) -> str:
    return json.dumps(vector)


def parse_embedding_json(raw: str | None) -> list[float]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
        return [float(item) for item in values]
    except Exception:
        return []


def ensure_post_embeddings(posts: list) -> int:
    """Backfill embedding vectors for existing posts when missing/empty."""
    updated = 0
    for post in posts:
        raw = getattr(post, "embedding_vector", None)
        if raw and raw not in {"[]", ""}:
            continue
        cleaned = _clean_for_nlp(getattr(post, "text", ""))
        embedding = _create_embedding(cleaned)
        post.embedding_vector = to_embedding_json(embedding)
        updated += 1
    return updated
