from __future__ import annotations

import re


def truncate(value: str, limit: int, suffix: str = "…") -> str:
    if len(value) <= limit:
        return value
    return value[: limit - len(suffix)].rstrip() + suffix


def split_lines(lines: list[str], limit: int = 1024) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        extra = len(line) + (1 if current else 0)
        if current and current_size + extra > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_size = len(line)
        else:
            current.append(line)
            current_size += extra
    if current:
        chunks.append("\n".join(current))
    return chunks or ["Nenhuma conta."]


def safe_channel_name(prefix: str, sale_id: int) -> str:
    cleaned = re.sub(r"[^a-z0-9-]", "-", prefix.lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-") or "gmail"
    return f"{cleaned}-{sale_id:04d}"[:100]
