"""Provider-neutral estimate for budgets, never a billing/tokenizer guarantee."""

import math
import re


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    return max(1, math.ceil(cjk * 1.5 + (len(text) - cjk) / 4))
