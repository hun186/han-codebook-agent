"""Offline-only regression checks for the model-settings UI layout/visibility."""
from __future__ import annotations

import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "src/han_codebook/static/index.html"
MOCK = ROOT / "vercel-demo/index.html"


class ModelSettingsLayoutTests(unittest.TestCase):
    def test_provider_form_has_independent_responsive_grid(self):
        for path in (LOCAL, MOCK):
            with self.subTest(path=str(path)):
                html = path.read_text(encoding="utf-8")
                settings = html.split('<section id="modelSettings"', 1)[1].split("</section>", 1)[0]
                self.assertIn('class="llm-settings-grid"', settings)
                self.assertNotIn('class="gridfield"', settings)
                self.assertIn('class="llm-model-picker"', settings)
                self.assertIn('id="llmModelCatalogWrap" hidden', settings)
                self.assertIn('id="llmAllowExternalWrap" hidden', settings)
                for target in ("llmPreset", "llmModel", "llmModelChoices", "llmUrl",
                               "llmTimeout", "llmKeyEnv", "llmMaxOutputTokens",
                               "llmAllowLAN", "llmAllowExternal"):
                    self.assertEqual(len(re.findall(r'id="'+target+r'"', settings)), 1, target)

    def test_css_limits_intrinsic_widths_and_honors_dynamic_hidden_labels(self):
        for path in (LOCAL, MOCK):
            with self.subTest(path=str(path)):
                html = path.read_text(encoding="utf-8")
                css = html.split("<style>", 1)[1].split("</style>", 1)[0]
                self.assertIn("[hidden]{display:none!important}", css)
                self.assertIn(".llm-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))", css)
                self.assertIn(".llm-settings-grid>div{min-width:0}", css)
                self.assertIn(".llm-model-picker{display:grid;grid-template-columns:minmax(0,1fr) auto", css)
                self.assertIn("@media(max-width:740px)", css)
                self.assertIn(".llm-model-picker{grid-template-columns:minmax(0,1fr)}", css)

    def test_provider_switch_only_exposes_relevant_permission_and_help(self):
        local = LOCAL.read_text(encoding="utf-8")
        mock = MOCK.read_text(encoding="utf-8")
        for html in (local, mock):
            self.assertIn("el('llmAllowLANWrap').hidden=deep", html)
            self.assertIn("el('llmAllowExternalWrap').hidden=!deep", html)
            self.assertIn("el('llmLANHelp').hidden=deep", html)
            self.assertIn("el('llmDeepInfraHelp').hidden=!deep", html)
            self.assertIn('id="llmDeepInfraHelp" class="muted llm-provider-help" hidden', html)
            self.assertIn('id="llmAllowLANWrap"', html)
            self.assertIn("192.168.0.134", html)


if __name__ == "__main__":
    unittest.main()
