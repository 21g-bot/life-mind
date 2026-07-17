from __future__ import annotations

import hashlib
import unittest
import uuid
import zipfile

from life_mind import __version__
from tools import check_public_release as release
from tools import verify_windows_release as windows_release


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

    def test_release_version_is_consistent_across_package_metadata_and_notes(self) -> None:
        numeric = tuple(int(part) for part in __version__.split(".")) + (0,)
        normalized_numeric = "(" + ",".join(str(part) for part in numeric) + ")"
        version_resource = (release.ROOT / "packaging" / "windows_version_info.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"filevers={normalized_numeric}", version_resource.replace(" ", ""))
        self.assertIn(f"prodvers={normalized_numeric}", version_resource.replace(" ", ""))
        self.assertIn(f"StringStruct('ProductVersion', '{__version__}')", version_resource)
        self.assertTrue((release.ROOT / "docs" / "releases" / f"v{__version__}.md").is_file())

    def test_windows_release_verifier_accepts_only_the_public_portable_layout(self) -> None:
        (release.ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        marker = uuid.uuid4().hex
        archive_path = release.ROOT / "tmp" / f"LIFE-Mind-v0.1.0-{marker}.zip"
        checksum_path = release.ROOT / "tmp" / f"LIFE-Mind-v0.1.0-{marker}.sha256"
        try:
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("LIFE-Mind/LIFE-Mind.exe", b"MZ" + b"\0" * 32)
                archive.writestr("LIFE-Mind/LICENSE", "Apache License 2.0")
                archive.writestr("LIFE-Mind/NOTICE", "LIFE-Mind")
                archive.writestr("LIFE-Mind/README.md", "# LIFE-Mind")
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")

            self.assertEqual(
                windows_release.validate_windows_release(archive_path, checksum_path),
                [],
            )

            with zipfile.ZipFile(archive_path, "a") as archive:
                archive.writestr("LIFE-Mind/data/private.db", b"private")
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
            errors = windows_release.validate_windows_release(archive_path, checksum_path)
            self.assertTrue(any("私人或本地目录" in error for error in errors))
            self.assertTrue(any("运行数据库" in error for error in errors))
        finally:
            archive_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
