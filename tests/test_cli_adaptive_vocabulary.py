"""CLI and YAML truly opt into automatic vocabulary, not a dead option."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.cli import main


def stub_result():
    return {"case_id": "fictional-cli", "known_code_count": 0,
            "unknown_code_count": 1, "metadata_used": True,
            "agent_rounds_completed": 3, "proposals": {}, "decoded_messages": []}


class CLIAutoVocabularyTests(unittest.TestCase):
    def test_cli_flag_enables_generation_and_skip_policy(self):
        with TemporaryDirectory() as td:
            dest = str(Path(td) / "report.json")
            with patch("han_codebook.cli.load_case", return_value={"fictional": True}), \
                 patch("han_codebook.cli.run_agent",
                       return_value=stub_result()) as runner:
                self.assertEqual(main([
                    "fictional.json", "--rounds", "3",
                    "--adaptive-vocabulary", "--vocab-zero-patience", "2",
                    "--out", dest]), 0)
            self.assertTrue(runner.call_args.kwargs["adaptive_vocabulary"])
            self.assertEqual(runner.call_args.kwargs["vocab_zero_patience"], 2)
            self.assertTrue(Path(dest).is_file())

    def test_legacy_cli_remains_static_until_opted_in(self):
        with TemporaryDirectory() as td:
            dest = str(Path(td) / "report.json")
            with patch("han_codebook.cli.load_case", return_value={"fictional": True}), \
                 patch("han_codebook.cli.run_agent",
                       return_value=stub_result()) as runner:
                self.assertEqual(main([
                    "fictional.json", "--rounds", "3",
                    "--out", dest]), 0)
            self.assertFalse(runner.call_args.kwargs["adaptive_vocabulary"])

    def test_config_mode_enables_generation_without_flag(self):
        with TemporaryDirectory() as td:
            cfg = {"project": {"case": "fictional.json"},
                   "analysis": {"rounds": 3, "adaptive_vocabulary": True},
                   "llm": {}}
            with patch("han_codebook.cli.load_settings", return_value=cfg), \
                 patch("han_codebook.cli.load_case", return_value={"fictional": True}), \
                 patch("han_codebook.cli.run_agent",
                       return_value=stub_result()) as runner:
                self.assertEqual(main([
                    "--config", "fake.yml", "--out", str(Path(td)/"out.json")]), 0)
            self.assertTrue(runner.call_args.kwargs["adaptive_vocabulary"])

    def test_automatic_vocabulary_refuses_zero_rounds(self):
        with self.assertRaises(SystemExit) as exc:
            main(["fictional.json", "--rounds", "0", "--adaptive-vocabulary"])
        self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
