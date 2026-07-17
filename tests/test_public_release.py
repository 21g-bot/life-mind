from __future__ import annotations

import unittest

from tools import check_public_release as release


class PublicReleaseBoundaryTests(unittest.TestCase):
    def test_private_paths_are_rejected_but_character_readme_is_public(self) -> None:
        self.assertTrue(release._is_forbidden("docs/CHARACTER_SEED.md"))
        self.assertTrue(release._is_forbidden("simulations/mvp_growth.json"))
        self.assertTrue(release._is_forbidden("assets/character/private/frame_000.png"))
        self.assertFalse(release._is_forbidden("assets/character/README.md"))

    def test_private_identity_terms_are_detected(self) -> None:
        private_name = "Lu" + "mi"
        private_identity = "sun" + "flower-girl"
        private_motif = "向" + "日葵"

        self.assertTrue(release._private_identity_hits(private_name))
        self.assertTrue(release._private_identity_hits(private_identity))
        self.assertTrue(release._private_identity_hits(private_motif))
        self.assertFalse(release._private_identity_hits("小芽（演示）"))

    def test_license_and_notice_are_present(self) -> None:
        license_text = (release.ROOT / "LICENSE").read_text(encoding="utf-8")
        notice_text = (release.ROOT / "NOTICE").read_text(encoding="utf-8")

        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn("不语 (Bùyǔ, GitHub: 21g-bot)", notice_text)


if __name__ == "__main__":
    unittest.main()
