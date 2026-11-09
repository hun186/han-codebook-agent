"""Word export preserves uncertain display while keeping original candidate table."""
from io import BytesIO
import unittest

from docx import Document
from han_codebook.report_docx import investigation_docx


class WordUncertaintyReportTests(unittest.TestCase):
    def test_word_respects_cautious_reading_and_legacy_fallback(self):
        result = {
            "case_id": "fictional",
            "metadata_used": False,
            "agent_rounds_completed": 0,
            "proposals": {"123": {
                "term": "中央站", "status": "hypothesis_unverified",
                "presentation_abstained": True}},
            "hypothesis_quality": {
                "presentation_abstained_code_count": 1,
                "near_tied_unverified_code_count": 1,
                "dominant_unverified_term_code_count": 1,
            },
            "decoded_messages": [
                {"id": "M1", "domain_inferred": None,
                 "reading": "中央站", "cautious_reading": "[123:待判]",
                 "verified_codes": 0, "total_codes": 1},
                {"id": "M2", "domain_inferred": None,
                 "reading": "舊版候選", "verified_codes": 0, "total_codes": 1},
            ],
        }
        doc = Document(BytesIO(investigation_docx(result, [])))
        paragraphs = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("推論不確定性", paragraphs)
        rows = [[c.text for c in row.cells] for row in doc.tables[-1].rows]
        self.assertIn("[123:待判]", str(rows))
        self.assertIn("舊版候選", str(rows))
        self.assertNotIn("中央站", str(rows))
        # Raw Top-1 is still visible in the separate code-candidate table.
        self.assertTrue(any("中央站" in cell.text
                            for table in doc.tables[:-1]
                            for row in table.rows for cell in row.cells))


if __name__ == "__main__":
    unittest.main()
