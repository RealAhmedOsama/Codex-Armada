"""Packaged configuration, schemas, and prompt templates."""

from pathlib import Path


def resource_path(*parts: str) -> Path:
    return Path(__file__).resolve().parent.joinpath(*parts)


__all__ = ["resource_path"]
