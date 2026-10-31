import os
import shutil
import tempfile
import unittest
from unittest import mock

from jobweaver import db

# Point db at a throwaway SQLite file before importing server
_TMP = tempfile.mkdtemp(prefix="gj-studio-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import server  # noqa: E402
from jobweaver import user_assets  # noqa: E402
from jobweaver import generators  # noqa: E402


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class StudioDocumentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-studio-paths-")
        patcher = mock.patch.multiple(
            user_assets,
            BASE_DIR=self.tmp_dir,
            PROFILES_DIR=os.path.join(self.tmp_dir, "profiles"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _default_user():
        return {"id": 1, "username": db.DEFAULT_USER_USERNAME}

    @staticmethod
    def _user2():
        return {"id": 2, "username": "sam"}

    def test_templates_endpoint(self):
        res = server.list_available_templates(user=self._default_user())
        self.assertIn("templates", res)

    def test_crud_document_flow(self):
        # 1. Create document
        create_req = server.CreateDocumentRequest(
            title="My Test CV",
            doc_type="cv",
            content=r"""\documentclass{article}
\begin{document}
Hello World Test CV
\end{document}
"""
        )
        created = server.create_studio_document(create_req, user=self._default_user())
        self.assertIn("id", created)
        self.assertEqual(created["title"], "My Test CV")
        doc_id = created["id"]

        # 2. List documents
        doc_list = server.list_studio_documents(user=self._default_user())
        self.assertEqual(len(doc_list["documents"]), 1)
        self.assertEqual(doc_list["documents"][0]["id"], doc_id)

        # 3. Multi-user isolation: user2 sees no documents
        doc_list_u2 = server.list_studio_documents(user=self._user2())
        self.assertEqual(len(doc_list_u2["documents"]), 0)

        # 4. Get document
        doc = server.get_studio_document(doc_id, user=self._default_user())
        self.assertEqual(doc["title"], "My Test CV")
        self.assertIn("Hello World Test CV", doc["content"])

        # 5. Update document
        update_req = server.UpdateDocumentRequest(
            title="Updated Title",
            content=r"""\documentclass{article}
\begin{document}
Updated Content
\end{document}
"""
        )
        up_res = server.update_studio_document(doc_id, update_req, user=self._default_user())
        self.assertTrue(up_res["success"])

        # Check update reflected
        doc_after = server.get_studio_document(doc_id, user=self._default_user())
        self.assertEqual(doc_after["title"], "Updated Title")
        self.assertIn("Updated Content", doc_after["content"])

        # 6. Delete document
        del_res = server.delete_studio_document(doc_id, user=self._default_user())
        self.assertTrue(del_res["success"])

        doc_list_empty = server.list_studio_documents(user=self._default_user())
        self.assertEqual(len(doc_list_empty["documents"]), 0)

    def test_compile_error_parsing(self):
        log_sample = r"""This is pdfTeX, Version 3.141592653-2.6-1.40.24
! Undefined control sequence.
l.14 \unknowncommand{test}
Here is how much of TeX's memory you used...
"""
        diag = generators.parse_pdflatex_error(log_sample)
        self.assertEqual(diag["line"], 14)
        self.assertIn("Undefined control sequence", diag["message"])
        self.assertEqual(diag["snippet"], "\\unknowncommand{test}")

    def test_job_doc_ai_versions_and_restore(self):
        draft_dir = os.path.join(self.tmp_dir, "drafts", "test_co_1")
        os.makedirs(draft_dir, exist_ok=True)

        # Initial state: empty
        v_init = server._get_ai_versions(draft_dir)
        self.assertEqual(v_init, {"cv": [], "letter": []})

        # Save some versions
        v_init["cv"].append({
            "id": "1001",
            "timestamp": 1001,
            "date_str": "10.09 11:00",
            "instruction": "Translate to German",
            "label": 'Before: "Translate to German"',
            "tex": "% Original English CV",
            "engine": "latex"
        })
        v_init["cv"].append({
            "id": "1000",
            "timestamp": 1000,
            "date_str": "10.09 10:30",
            "instruction": "Sharpen bullets",
            "label": 'Before: "Sharpen bullets"',
            "tex": "% Draft 1",
            "engine": "latex"
        })
        server._save_ai_versions(draft_dir, v_init)

        # Retrieve and assert
        v_loaded = server._get_ai_versions(draft_dir)
        self.assertEqual(len(v_loaded["cv"]), 2)
        self.assertEqual(v_loaded["cv"][0]["id"], "1001")

        # Test snapshot creation code path with mock AI edit
        with mock.patch("jobweaver.server.ai_surgical_edit_latex", return_value="% Modified"):
            with mock.patch("jobweaver.server.compile_latex", return_value=(True, "")):
                with mock.patch("jobweaver.server.convert_pdf_to_images", return_value=[]):
                    with mock.patch("jobweaver.db.get_job_by_id", return_value={"id": "j1", "company": "TestCo"}):
                        req = server.JobDocAiEditRequest(
                            document_type="cv",
                            tex="% Pre-edit tex",
                            instruction="Translate CV to German",
                        )
                        res = server.ai_edit_job_document("j1", req, user=self._default_user())
                        self.assertTrue(res["success"])
                        self.assertIn("ai_versions", res)
                        self.assertEqual(res["ai_versions"]["cv"][0]["instruction"], "Translate CV to German")
                        self.assertEqual(res["ai_versions"]["cv"][0]["tex"], "% Modified")
                        self.assertEqual(res["ai_versions"]["cv"][0]["label"], 'AI: "Translate CV to German"')
                        self.assertEqual(res["ai_versions"]["cv"][1]["tex"], "% Pre-edit tex")
                        self.assertEqual(res["active_version_id"], res["ai_versions"]["cv"][0]["id"])

                        # Now test non-destructive restore back to the pre-edit version
                        target_pre_id = res["ai_versions"]["cv"][1]["id"]
                        restore_req = server.JobDocRestoreVersionRequest(
                            document_type="cv",
                            version_id=target_pre_id,
                        )
                        restore_res = server.restore_job_document_version("j1", restore_req, user=self._default_user())
                        self.assertTrue(restore_res["success"])
                        self.assertEqual(restore_res["restored_tex"], "% Pre-edit tex")
                        self.assertEqual(restore_res["active_version_id"], target_pre_id)
                        # Ensure both versions still exist in ai_versions (not deleted or popped!)
                        cv_vers = restore_res["ai_versions"]["cv"]
                        self.assertTrue(any(v["id"] == res["ai_versions"]["cv"][0]["id"] for v in cv_vers))
                        self.assertTrue(any(v["id"] == target_pre_id for v in cv_vers))

                        # Now test jumping forward again to the AI version!
                        ai_ver_id = res["ai_versions"]["cv"][0]["id"]
                        restore_ai_req = server.JobDocRestoreVersionRequest(
                            document_type="cv",
                            version_id=ai_ver_id,
                        )
                        restore_ai_res = server.restore_job_document_version("j1", restore_ai_req, user=self._default_user())
                        self.assertTrue(restore_ai_res["success"])
                        self.assertEqual(restore_ai_res["restored_tex"], "% Modified")
                        self.assertEqual(restore_ai_res["active_version_id"], ai_ver_id)

    def test_freshly_generated_document_seeding_and_manual_edits(self):
        draft_dir = os.path.join(user_assets.user_drafts_dir("admin"), "FreshCo_fresh_1")
        os.makedirs(draft_dir, exist_ok=True)
        # Simulate freshly generated CV written to disk with _v0 pristine backup
        pristine_tex = "% Pristine Generated CV"
        with open(os.path.join(draft_dir, "cv_fresh_1.tex"), "w", encoding="utf-8") as f:
            f.write(pristine_tex)
        with open(os.path.join(draft_dir, "cv_fresh_1_v0.tex"), "w", encoding="utf-8") as f:
            f.write(pristine_tex)

        with mock.patch("jobweaver.db.get_job_by_id", return_value={"id": "fresh_1", "company": "FreshCo"}):
            # 1. get_job_documents should automatically seed Original Draft into ai_versions.json
            doc_res = server.get_job_documents("fresh_1", user=self._default_user())
            self.assertTrue(doc_res["success"])
            self.assertEqual(len(doc_res["ai_versions"]["cv"]), 1)
            self.assertEqual(doc_res["ai_versions"]["cv"][0]["label"], "Original Draft")
            self.assertEqual(doc_res["ai_versions"]["cv"][0]["tex"], pristine_tex)

            # 2. User makes manual edits, then runs AI edit
            manual_edited_tex = "% Pristine Generated CV with My Manual Edits"
            with mock.patch("jobweaver.server.ai_surgical_edit_latex", return_value="% AI Output After Manual Edits"):
                with mock.patch("jobweaver.server.compile_latex", return_value=(True, "")):
                    with mock.patch("jobweaver.server.convert_pdf_to_images", return_value=[]):
                        ai_req = server.JobDocAiEditRequest(
                            document_type="cv",
                            tex=manual_edited_tex,
                            instruction="Sharpen technical bullets",
                        )
                        ai_res = server.ai_edit_job_document("fresh_1", ai_req, user=self._default_user())
                        self.assertTrue(ai_res["success"])
                        versions = ai_res["ai_versions"]["cv"]
                        # Should have 3 versions:
                        # [0] AI output
                        # [1] Before AI (containing manual edits)
                        # [2] Original Draft (the pristine generated document)
                        self.assertEqual(len(versions), 3)
                        self.assertEqual(versions[0]["label"], 'AI: "Sharpen technical bullets"')
                        self.assertEqual(versions[0]["tex"], "% AI Output After Manual Edits")
                        self.assertEqual(versions[1]["label"], 'Before: "Sharpen technical bullets"')
                        self.assertEqual(versions[1]["tex"], manual_edited_tex)
                        self.assertEqual(versions[2]["label"], "Original Draft")
                        self.assertEqual(versions[2]["tex"], pristine_tex)

                        # 3. User reverts to version before AI (restores manual edits)
                        restore_manual = server.restore_job_document_version(
                            "fresh_1",
                            server.JobDocRestoreVersionRequest(document_type="cv", version_id=versions[1]["id"]),
                            user=self._default_user(),
                        )
                        self.assertEqual(restore_manual["restored_tex"], manual_edited_tex)

                        # 4. User reverts all the way back to Original Draft (pristine generated)
                        restore_orig = server.restore_job_document_version(
                            "fresh_1",
                            server.JobDocRestoreVersionRequest(document_type="cv", version_id=versions[2]["id"]),
                            user=self._default_user(),
                        )
                        self.assertEqual(restore_orig["restored_tex"], pristine_tex)


if __name__ == "__main__":
    unittest.main()

