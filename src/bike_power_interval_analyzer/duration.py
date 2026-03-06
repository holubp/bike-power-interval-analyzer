"""Duration parsing helpers."""

from __future__ import annotations


def parse_duration_to_seconds(raw: str) -> float:
    """Parse duration text into seconds.

    Supported forms:
    - integer or float seconds (e.g. ``"30"``, ``"12.5"``)
    - ``MM:SS``
    - ``HH:MM:SS``

    Args:
        raw: Input duration string.

    Returns:
        Duration in seconds.

    Raises:
        ValueError: If the input cannot be parsed or is non-positive.
    """
    text = raw.strip()
    if not text:
        raise ValueError("Duration must not be empty.")

    if ":" not in text:
        try:
            seconds = float(text)
        except ValueError as exc:
            raise ValueError(
                f"Invalid duration '{raw}'. Expected seconds or MM:SS or HH:MM:SS."
            ) from exc
        if seconds <= 0:
            raise ValueError(f"Duration must be > 0 seconds, got {seconds}.")
        return seconds

    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(
            f"Invalid duration '{raw}'. Use MM:SS or HH:MM:SS when ':' is used."
        )

    try:
        numeric_parts = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError(
            f"Invalid duration '{raw}'. All colon-separated parts must be numeric."
        ) from exc

    for i, value in enumerate(numeric_parts):
        if value < 0:
            raise ValueError(f"Duration part #{i + 1} must be >= 0, got {value}.")

    if len(numeric_parts) == 2:
        minutes, seconds = numeric_parts
        if seconds >= 60:
            raise ValueError(
                f"Invalid MM:SS duration '{raw}'. Seconds part must be < 60."
            )
        total = minutes * 60 + seconds
    else:
        hours, minutes, seconds = numeric_parts
        if minutes >= 60 or seconds >= 60:
            raise ValueError(
                f"Invalid HH:MM:SS duration '{raw}'. Minutes and seconds must be < 60."
            )
        total = hours * 3600 + minutes * 60 + seconds

    if total <= 0:
        raise ValueError(f"Duration must be > 0 seconds, got {total}.")
    return total


def parse_inner_interval_lengths(values: list[object] | None) -> list[float]:
    """Parse ``--inner-intlen`` values into positive seconds.

    Args:
        values: Raw values from CLI. ``None`` means default should be used.

    Returns:
        Parsed list of inner interval lengths in seconds.

    Raises:
        ValueError: If any provided value is invalid.
    """
    if values is None:
        return [10.0]
    if len(values) == 0:
        return []

    parsed: list[float] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            raise ValueError("Inner interval length entries must not be empty strings.")
        seconds = parse_duration_to_seconds(text)
        if seconds <= 0:
            raise ValueError(f"Inner interval length must be > 0, got {seconds}.")
        parsed.append(seconds)
    return parsed
