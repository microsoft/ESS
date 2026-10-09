import argparse
import csv
import sys
from pathlib import Path

from topic_classifier import classify, load_rules


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rules = load_rules(args.taxonomy)
    corpus = read_csv(args.corpus)
    results = []

    for case in corpus:
        result = classify(case["Prompt"], case["Locale"], rules)
        passed = result["topic"] == case["ExpectedTopic"] and result["vertical"] == case["ExpectedVertical"]
        results.append(
            {
                **case,
                "PredictedTopic": result["topic"],
                "PredictedVertical": result["vertical"],
                "MatchedTerms": result["matched_terms"],
                "Passed": passed,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    failures = [item for item in results if not item["Passed"]]
    print(f"{len(results) - len(failures)}/{len(results)} cases passed")
    for item in failures:
        print(
            f"{item['CaseId']}: expected {item['ExpectedTopic']} / {item['ExpectedVertical']}, "
            f"got {item['PredictedTopic']} / {item['PredictedVertical']}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
