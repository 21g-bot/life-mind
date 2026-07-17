from __future__ import annotations

import unittest

from life_mind.blind_review import evaluate_blind_responses


ANSWER = {
    "review_id": "review-1",
    "card_digest": "digest-1",
    "card_roles": {"A": "baseline", "B": "evidence_arc"},
}


def form(reviewer_id: str, *, choice: str = "B", complete: bool = True) -> dict[str, object]:
    return {
        "review_id": "review-1",
        "card_digest": "digest-1",
        "response": {
            "reviewer_id": reviewer_id,
            "life_outside_task_card": choice,
            "behaviour_evidence": ["主动休息", "为自己画画"] if complete else [""],
            "pressure_response_card": choice,
            "confidence": 4 if complete else 0,
            "key_evidence": "先暂停并复盘具体错误" if complete else "",
        },
    }


class BlindReviewAggregationTests(unittest.TestCase):
    def test_fewer_than_five_complete_human_forms_remains_pending(self) -> None:
        report = evaluate_blind_responses([form(f"r{index}") for index in range(4)], ANSWER)

        self.assertEqual(report["status"], "pending")
        self.assertEqual(report["complete_forms"], 4)
        self.assertEqual(report["passing_forms"], 4)

    def test_four_of_five_matching_forms_pass_the_gate(self) -> None:
        forms = [form(f"r{index}") for index in range(4)]
        forms.append(form("r4", choice="A"))

        report = evaluate_blind_responses(forms, ANSWER)

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["complete_forms"], 5)
        self.assertEqual(report["passing_forms"], 4)

    def test_incomplete_or_duplicate_forms_do_not_close_the_gate(self) -> None:
        forms = [form("same"), form("same"), form("r2", complete=False)]

        report = evaluate_blind_responses(forms, ANSWER)

        self.assertEqual(report["status"], "pending")
        self.assertEqual(report["unique_reviewers"], 2)
        self.assertEqual(report["complete_forms"], 1)
        self.assertTrue(report["reviewers"][1]["issues"])

    def test_modified_card_version_is_rejected(self) -> None:
        changed = form("r1")
        changed["card_digest"] = "modified"

        report = evaluate_blind_responses(
            [changed], ANSWER, minimum_reviewers=1, minimum_passes=1
        )

        self.assertEqual(report["status"], "pending")
        self.assertIn("卡片内容摘要与答案表不一致", report["reviewers"][0]["issues"])


if __name__ == "__main__":
    unittest.main()
