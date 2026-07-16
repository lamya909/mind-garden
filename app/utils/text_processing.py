import re
from typing import List


def clean_text(text: str) -> str:
    """Clean input text while preserving emotional content and emojis."""
    text = text.strip()
    text = re.sub(r"https?://\\S+|www\\.\\S+", "", text)
    text = re.sub(r"\\s+", " ", text)
    return text


def simple_tokenize(text: str) -> List[str]:
    """Basic tokenizer used for telemetry and debugging NLP behavior."""
    return re.findall(r"[\\w']+", text.lower())
