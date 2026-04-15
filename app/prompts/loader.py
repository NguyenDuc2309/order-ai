from functools import lru_cache
from pathlib import Path

import yaml


PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=8)
def load_prompt(filename: str) -> dict:
    path = PROMPTS_DIR / filename
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)
