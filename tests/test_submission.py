import unittest
from pathlib import Path
from scripts.check_submission import local_links, secret_kinds
from scripts.export_submission import exclusion_reason


class SubmissionChecks(unittest.TestCase):
    def test_links_ignore_web_and_fences_decode_spaces(self):
        md = "[A](a%20b.md) [B](https://example.org)\n```\n[x](missing)\n```\n![C](x.svg#id)"
        self.assertEqual(local_links(md), ["a b.md", "x.svg"])

    def test_secret_findings_do_not_echo_values(self):
        token = "gh" + "p_" + "A" * 36
        self.assertEqual(secret_kinds(token), ["github_token"])
        self.assertEqual(secret_kinds("export SLACK_WEBHOOK_URL; <MODEL_PATH>"), [])

    def test_export_keeps_source_but_not_model_photos_profiles_or_large_files(self):
        self.assertIsNone(
            exclusion_reason(Path("diagnostics/mps_static/native_query.cu"), 100)
        )
        self.assertIsNone(
            exclusion_reason(Path("results/sustained/run/plots/e2e.png"), 100)
        )
        self.assertIsNotNone(exclusion_reason(Path("results/raw/trace.sqlite"), 100))
        self.assertIsNotNone(exclusion_reason(Path("results/raw/bus.png"), 100))
        self.assertIsNotNone(exclusion_reason(Path("weights/model.pt"), 100))
        self.assertIsNotNone(
            exclusion_reason(Path("results/raw/data.jsonl"), 51 * 1024 * 1024)
        )


class BurstReportScope(unittest.TestCase):
    def test_burst_table_has_no_sustained_rows_and_keeps_seven_conditions(self):
        from scripts.render_submission_tables import render_burst

        text = render_burst()
        self.assertNotIn("지속", text)
        self.assertNotIn("req/s", text)
        self.assertIn("static-q8-y40", text)
        self.assertEqual(
            sum(
                line.startswith("|control|")
                or line.startswith("|mps-only|")
                or line.startswith("|static-q")
                for line in text.splitlines()
            ),
            7,
        )


class BurstKeyMetricTable(unittest.TestCase):
    def test_summary_distinguishes_mean_p95_and_internal_ttft(self):
        from scripts.render_submission_tables import render_burst

        text = render_burst()
        self.assertIn("YOLO 요청 E2E 평균", text)
        self.assertIn("Qwen 내부 TTFT", text)
        self.assertIn("+150.60%", text)


class FrozenBaselineReference(unittest.TestCase):
    def test_baseline_audit_does_not_depend_on_mutable_branch_tip(self):
        import subprocess
        from unittest.mock import patch
        from scripts.check_submission import baseline_check, BASELINE

        original = subprocess.check_output

        def independent(command, *args, **kwargs):
            if command == ["git", "rev-parse", "baseline"]:
                return "f" * 40 + "\n"
            return original(command, *args, **kwargs)

        with patch(
            "scripts.check_submission.subprocess.check_output", side_effect=independent
        ):
            result = baseline_check()
        self.assertEqual(result["ref"], BASELINE)
        self.assertEqual(result["verified_files"], 677)
