def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0 if a else 0.0
    if not a or not b:
        return 0.0
    window = max(len(a), len(b)) // 2 - 1
    a_matched = [False] * len(a)
    b_matched = [False] * len(b)
    matches = 0
    for i, char in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not b_matched[j] and b[j] == char:
                a_matched[i] = b_matched[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    a_seq = [c for c, m in zip(a, a_matched, strict=True) if m]
    b_seq = [c for c, m in zip(b, b_matched, strict=True) if m]
    transpositions = sum(x != y for x, y in zip(a_seq, b_seq, strict=True)) / 2
    return (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3


def jaro_winkler(a: str, b: str, prefix_scale: float = 0.1) -> float:
    """Jaro-Winkler similarity in [0, 1]; the common prefix (up to 4 chars) is boosted."""
    similarity = jaro(a, b)
    prefix = 0
    for x, y in zip(a[:4], b[:4], strict=False):
        if x != y:
            break
        prefix += 1
    return similarity + prefix * prefix_scale * (1 - similarity)
