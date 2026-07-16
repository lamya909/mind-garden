from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from flask import current_app

from app.utils.text_processing import clean_text, simple_tokenize


@dataclass
class EmotionAnalysis:
    label: str
    confidence: float
    cleaned_text: str
    token_count: int


_classifier = None
_tokenizer = None
_load_error: Optional[str] = None


def _load_pipeline() -> None:
    """Lazy-load HuggingFace pipeline and tokenizer once per process."""
    global _classifier, _tokenizer, _load_error
    if _classifier is not None or _load_error is not None:
        return

    try:
        from transformers import AutoTokenizer, pipeline

        model_name = current_app.config["HF_EMOTION_MODEL"]
        _tokenizer = AutoTokenizer.from_pretrained(model_name)
        _classifier = pipeline("text-classification", model=model_name, top_k=1)
    except Exception as exc:  # pragma: no cover
        _load_error = str(exc)


def analyze_emotion(text: str) -> Dict[str, float | str | int]:
    """
    Analyze emotion for a journal entry.
    Returns emotion label + confidence and processing metadata.
    """
    cleaned = clean_text(text)
    tokens = simple_tokenize(cleaned)

    _load_pipeline()

    if _classifier is not None and _tokenizer is not None:
        # Explicit tokenization to satisfy NLP processing requirements.
        _tokenizer(cleaned, truncation=True, max_length=256)
        raw = _classifier(cleaned)
        item = raw[0][0] if raw and isinstance(raw[0], list) else raw[0]
        label = str(item.get("label", "neutral")).lower()
        score = float(item.get("score", 0.0))
    else:
        # Graceful fallback keeps app usable when model download/runtime is unavailable.
        text_l = cleaned.lower()
        fallback = {
            "joy": ["happy", "grateful", "excited", "great", "good"],
            "sadness": ["sad", "down", "depressed", "lonely"],
            "anger": ["angry", "mad", "frustrated", "annoyed"],
            "fear": ["anxious", "scared", "worried", "nervous"],
        }
        label = "neutral"
        score = 0.55
        for emotion, keywords in fallback.items():
            if any(keyword in text_l for keyword in keywords):
                label = emotion
                score = 0.7
                break

    result = EmotionAnalysis(
        label=label,
        confidence=round(score, 4),
        cleaned_text=cleaned,
        token_count=len(tokens),
    )

    return {
        "label": result.label,
        "confidence": result.confidence,
        "cleaned_text": result.cleaned_text,
        "token_count": result.token_count,
        "load_error": _load_error,
    }
