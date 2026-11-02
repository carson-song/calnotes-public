"""Compare eval runs side by side, with a paired significance test. Provided.

  python3 tools/compare_runs.py runs/*_fresh
  python3 tools/compare_runs.py runs/*_fresh --price claude-haiku-5-5=0.10/0.50 \
      --price claude-sonnet-5-5=2/10 --cache 0.1/1.25   # $ per million tokens; check the models' pricing pages

Two models scored on the same notes are compared note by note (McNemar's exact test): only the notes where
exactly one of them is right carry information. That's far more sensitive than comparing two percentages.
"""
import json
import sys
from math import comb, sqrt
from pathlib import Path


def ci95(p: float, n: int) -> float:
    return 1.96 * sqrt(p * (1 - p) / n) if n else 0.0


def mcnemar_p(a: dict, b: dict, field: str) -> tuple:
    only_a = sum(1 for i in a if a[i][field] and not b[i][field])
    only_b = sum(1 for i in a if b[i][field] and not a[i][field])
    n, k = only_a + only_b, min(only_a, only_b)
    p = min(1.0, 2 * sum(comb(n, j) for j in range(k + 1)) / 2 ** n) if n else 1.0
    return only_a, only_b, p


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--price", action="append", default=[], metavar="MODEL=IN/OUT",
                    help="$ per million input/output tokens, from the current pricing page")
    ap.add_argument("--cache", default="1/1", metavar="READ_X/WRITE_X",
                    help="cache read/write price as a multiple of the input price (check the pricing page)")
    a = ap.parse_args()
    price = {}
    for pr in a.price:
        name, _, v = pr.partition("=")
        pin, _, pout = v.partition("/")
        try:
            price[name] = (float(pin), float(pout))
        except ValueError:
            sys.exit(f"--price {pr}: use numbers, dollars per million input/output tokens, "
                     f"e.g. --price claude-sonnet-5-5=2/10")
    cache = tuple(float(x) for x in a.cache.split("/"))
    runs = []
    for d in a.runs:
        if (d / "metrics.json").exists() and (d / "correct.json").exists():
            runs.append((d, json.loads((d / "metrics.json").read_text()), json.loads((d / "correct.json").read_text())))
    if not runs:
        sys.exit("No run folders with metrics.json and correct.json given.")
    print(f"{'model':24} {'n':>4} {'type':>11} {'coarse':>7} {'goals':>11} {'s/note':>7} {'p95':>6} {'total':>7} "
          f"{'tok/note':>9} {'cached':>7} {'cost':>8}")
    for d, m, _ in runs:
        n, name = m["n"], m.get("model", d.name)
        t, g = m["type_acc_strict"], m["goal_links_exact"]
        cached = m.get("cache_read_tokens", 0)
        all_in = m.get("input_tokens", 0) + cached + m.get("cache_write_tokens", 0)
        cost = "local" if not name.startswith("claude") else "-"
        if name in price:
            pin, pout = price[name]
            usd = (m.get("input_tokens", 0) * pin + cached * pin * cache[0]
                   + m.get("cache_write_tokens", 0) * pin * cache[1] + m.get("output_tokens", 0) * pout) / 1e6
            cost = f"${usd:.2f}"
        c = m.get("type_acc_coarse")
        print(f"{name[:24]:24} {n:>4} {t:>5.0%} ±{ci95(t, n):<4.0%} {(f'{c:.0%}' if c is not None else '-'):>7}"
              f" {g:>5.0%} ±{ci95(g, n):<4.0%}"
              f" {m.get('seconds_per_item', 0):>6.1f}s {m.get('seconds_p95', 0):>5.1f}s"
              f" {m.get('seconds_total', 0) / 60:>5.1f}m {m.get('tokens_per_item', 0):>9,.0f}"
              f" {(cached / all_in if all_in else 0):>6.0%} {cost:>8}")
    print("\npaired (McNemar): notes only A got right / only B got right, p-value")
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            (_, ma, ca), (_, mb, cb) = runs[i], runs[j]
            if set(ca) != set(cb):
                print(f"  {ma.get('model')} vs {mb.get('model')}: different notes, skipped")
                continue
            for field in ("type", "goals"):
                oa, ob, p = mcnemar_p(ca, cb, field)
                print(f"  {ma.get('model')[:16]:16} vs {mb.get('model')[:16]:16} {field:5}  {oa:>3} / {ob:<3}  p={p:.3f}")


if __name__ == "__main__":
    main()
