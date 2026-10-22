import os
import shutil
import tempfile
import unittest
import base64
from unittest import mock

import db
import generators
import server
import user_assets
from pdf_fixture import pdf_bytes


class TestTypstSupport(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-typst-paths-")
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        db.set_db_path(self.db_path)
        db.init_db()
        os.makedirs(os.path.join(self.tmp_dir, "base-typst"), exist_ok=True)
        shutil.copy("base-typst/base-cv.typ", os.path.join(self.tmp_dir, "base-typst", "base-cv.typ"))
        shutil.copy("base-typst/base-cl.typ", os.path.join(self.tmp_dir, "base-typst", "base-cl.typ"))
        if os.path.exists("base-typst/base-cv-moderner.typ"):
            shutil.copy("base-typst/base-cv-moderner.typ", os.path.join(self.tmp_dir, "base-typst", "base-cv-moderner.typ"))

        patcher = mock.patch.multiple(
            user_assets,
            BASE_DIR=self.tmp_dir,
            PROFILES_DIR=os.path.join(self.tmp_dir, "profiles"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _user():
        return {"id": 1, "username": "admin"}

    def test_compile_typst_success(self):
        with tempfile.TemporaryDirectory() as td:
            typ_path = os.path.join(td, "test.typ")
            with open(typ_path, "w", encoding="utf-8") as f:
                f.write('= Hello World\n#set text(font: ("Arial", "Helvetica Neue"), size: 10pt)\nThis is a test.')

            ok, msg = generators.compile_typst(
                folder=td,
                filename="test.typ",
                output_filename="test.pdf",
                output_dir=td,
                generate_previews=True,
            )
            self.assertTrue(ok, f"compile_typst failed: {msg}")
            out_pdf = os.path.join(td, "test.pdf")
            self.assertTrue(os.path.exists(out_pdf))
            self.assertGreater(os.path.getsize(out_pdf), 0)
            preview_img = os.path.join(td, "preview-1.png")
            self.assertTrue(os.path.exists(preview_img))
            self.assertGreater(os.path.getsize(preview_img), 0)

    def test_compile_typst_syntax_error(self):
        with tempfile.TemporaryDirectory() as td:
            typ_path = os.path.join(td, "bad.typ")
            with open(typ_path, "w", encoding="utf-8") as f:
                f.write('#let x = (\nThis has an unclosed parenthesis')

            ok, log = generators.compile_typst(
                folder=td,
                filename="bad.typ",
                output_filename="bad.pdf",
                output_dir=td,
            )
            self.assertFalse(ok)
            diag = generators.parse_typst_error(log)
            self.assertIsNotNone(diag.get("line"))
            self.assertIn("Line", diag.get("message", ""))

    def test_compile_studio_document_detects_typst(self):
        with tempfile.TemporaryDirectory() as td:
            typ_path = os.path.join(td, "document.typ")
            with open(typ_path, "w", encoding="utf-8") as f:
                f.write('= Document Title\n#set text(font: ("Arial", "Helvetica Neue"), size: 10pt)\nContent goes here.')

            ok, msg = generators.compile_studio_document(td)
            self.assertTrue(ok, f"compile_studio_document failed: {msg}")
            out_pdf = os.path.join(td, "document.pdf")
            self.assertTrue(os.path.exists(out_pdf))
            self.assertGreater(os.path.getsize(out_pdf), 0)

    def test_parse_typst_error_formats(self):
        # Short format
        short_log = "base-cv.typ:14:5: error: unknown variable: undefined_var"
        diag = generators.parse_typst_error(short_log)
        self.assertEqual(diag["line"], 14)
        self.assertEqual(diag["column"], 5)
        self.assertIn("unknown variable", diag["message"])

        # Human format
        human_log = "error: unclosed delimiter\n  ┌─ <stdin>:1:4\n  │\n1 │ #foo(bar\n  │     ^"
        diag2 = generators.parse_typst_error(human_log)
        self.assertEqual(diag2["line"], 1)
        self.assertEqual(diag2["column"], 4)
        self.assertIn("unclosed delimiter", diag2["message"])

        # Empty fallback
        diag_empty = generators.parse_typst_error("")
        self.assertIsNone(diag_empty["line"])

    def test_api_templates_include_typst(self):
        res = server.list_available_templates(user=self._user())
        self.assertIn("templates", res)
        tmpls = res["templates"]
        typst_tmpls = [t for t in tmpls if t.get("engine") == "typst"]
        self.assertGreaterEqual(len(typst_tmpls), 1)
        cv_tmpl = next((t for t in typst_tmpls if t["doc_type"] == "cv"), None)
        self.assertIsNotNone(cv_tmpl)
        self.assertIn("Typst", cv_tmpl["title"])

    def test_api_create_and_compile_typst_document(self):
        user = self._user()
        # 1. Create document with Typst engine
        create_req = server.CreateDocumentRequest(
            title="Typst Test Resume",
            doc_type="cv",
            engine="typst",
            template_source="base-typst/base-cv.typ",
        )
        doc = server.create_studio_document(create_req, user=user)
        doc_id = doc["id"]
        self.assertEqual(doc["engine"], "typst")
        self.assertTrue(doc["has_pdf"])
        self.assertGreater(len(doc["preview_urls"]), 0)

        # 2. Get document
        get_doc = server.get_studio_document(doc_id, user=user)
        self.assertEqual(get_doc["engine"], "typst")
        self.assertIn("Alex Muster", get_doc["content"])

        # 3. Recompile document
        compile_req = server.CompileDocumentRequest(content=get_doc["content"] + "\n// extra comment")
        c_data = server.compile_studio_document_api(doc_id, req=compile_req, user=user)
        self.assertTrue(c_data["success"])
        self.assertTrue(c_data["has_pdf"])

        # 4. List documents
        doc_list = server.list_studio_documents(user=user)
        matching = next((d for d in doc_list["documents"] if d["id"] == doc_id), None)
        self.assertIsNotNone(matching)
        self.assertEqual(matching["engine"], "typst")

        # 5. Clean up
        del_res = server.delete_studio_document(doc_id, user=user)
        self.assertTrue(del_res["success"])

    def test_api_client_pdf_base64_sync(self):
        user = self._user()
        create_req = server.CreateDocumentRequest(
            title="Typst Client Sync Test",
            doc_type="cv",
            engine="typst",
            template_source="base-typst/base-cv.typ",
        )
        doc = server.create_studio_document(create_req, user=user)
        doc_id = doc["id"]

        fake_pdf = pdf_bytes()
        fake_b64 = base64.b64encode(fake_pdf).decode("ascii")

        # 1. Update document with client PDF base64
        upd_req = server.UpdateDocumentRequest(
            content="= Updated in WASM",
            pdf_base64=fake_b64,
        )
        res = server.update_studio_document(doc_id, req=upd_req, user=user)
        self.assertTrue(res["success"])

        # Check file on disk
        doc_dir = server._resolved_safe_path(doc_id, user_assets.user_documents_dir(user["username"]))
        pdf_path = os.path.join(doc_dir, "document.pdf")
        self.assertTrue(os.path.exists(pdf_path))
        with open(pdf_path, "rb") as f:
            self.assertEqual(f.read(), fake_pdf)

        # 2. Compile document with client PDF base64 (zero-CLI path)
        comp_req = server.CompileDocumentRequest(
            content="= Recompiled in WASM",
            pdf_base64=fake_b64,
        )
        c_res = server.compile_studio_document_api(doc_id, req=comp_req, user=user)
        self.assertTrue(c_res["success"])
        self.assertTrue(c_res["has_pdf"])

        server.delete_studio_document(doc_id, user=user)

    def test_job_documents_typst_wasm_sync(self):
        user = self._user()
        username = user["username"]
        job_id = "test_typst_job_1"
        job_dict = {
            "id": job_id,
            "title": "Backend Engineer",
            "company": "TypstTech GmbH",
            "description": "Python and Typst developer needed",
            "url": "https://example.com/job/1",
        }
        db.upsert_job(job_dict, user_id=user["id"])

        fake_pdf = pdf_bytes()
        fake_b64 = base64.b64encode(fake_pdf).decode("ascii")

        # 1. Compile CV via client-side PDF base64
        comp_req = server.JobDocCompileRequest(
            document_type="cv",
            tex="// Typst CV content\n#set text(10pt)\n= Alex",
            pdf_base64=fake_b64,
        )
        c_res = server.compile_job_document(job_id, req=comp_req, user=user)
        self.assertTrue(c_res["success"])
        self.assertIn("cv_draft_test_typst_job_1.pdf", c_res["pdf_url"])

        # 2. Verify get_job_documents detects typst engine
        docs_res = server.get_job_documents(job_id, user=user)
        self.assertTrue(docs_res["success"])
        self.assertTrue(docs_res["has_cv"])
        self.assertEqual(docs_res["cv_engine"], "typst")
        self.assertIn("#set text(10pt)", docs_res["cv_tex"])

        # 3. Finalize with cv_pdf_base64
        fin_req = server.JobDocFinalizeRequest(
            document_type="cv",
            cv_pdf_base64=fake_b64,
        )
        f_res = server.finalize_job_documents(job_id, req=fin_req, user=user)
        self.assertTrue(f_res["success"])
        self.assertIsNotNone(f_res["cv_url"])

    def test_load_document_engine_config(self):
        user = self._user()
        # Default with no config file in tmp_dir
        engine, template = server.load_document_engine_config(user)
        self.assertEqual(engine, "typst")
        self.assertEqual(template, "base-cv-moderner.typ")

        # Custom config
        import json
        cfg_path = os.path.join(self.tmp_dir, "scraper_config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({
                "auto_generate": {
                    "document_engine": "latex",
                    "typst_cv_template": "base-cv.typ"
                }
            }, f)

        engine, template = server.load_document_engine_config(user)
        self.assertEqual(engine, "latex")
        self.assertEqual(template, "base-cv.typ")


    @mock.patch("server.compile_job_document", return_value={"success": True})
    @mock.patch("server.reviewed_documents.generate")
    def test_try_generate_cv_pdf_typst_dispatch(self, mock_gen_typst, mock_compile_typst):
        user = self._user()
        job_id = "test_gen_cv_job"
        db.upsert_job({
            "id": job_id,
            "title": "Research Software Engineer",
            "cv_profile_override": "industry",
            "company": "CloudCo",
            "description": "Scientific research pipelines",
        }, user_id=user["id"])

        # Create CV-plaintext.txt in user directory
        user_dir = os.path.join(self.tmp_dir, "profiles", user["username"])
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, "CV-plaintext.txt"), "w", encoding="utf-8") as f:
            f.write("Alex Muster\nDeveloper")

        mock_gen_typst.return_value = "// Tailored Typst CV\n#set text(10pt)\n= Alex"
        mock_compile_typst.return_value = {"success": True}

        with mock.patch("server.finalize_job_documents", return_value={"success": True}):
            err = server._try_generate_cv_pdf(job_id, "test-model", "", user, engine="typst")
        self.assertIsNone(err)
        self.assertTrue(mock_gen_typst.called)
        self.assertEqual(mock_gen_typst.call_args[0][5], 'industry')
        self.assertTrue(mock_compile_typst.called)

    @mock.patch("server.compile_job_document", return_value={"success": True})
    @mock.patch("server.reviewed_documents.generate")
    def test_try_generate_letter_pdf_typst_dispatch(self, mock_gen_letter, mock_compile_typst):
        user = self._user()
        job_id = "test_gen_letter_job"
        db.upsert_job({
            "id": job_id,
            "title": "Research Software Engineer",
            "cv_profile_override": "industry",
            "company": "CloudCo",
            "description": "Scientific research pipelines",
        }, user_id=user["id"])

        user_dir = os.path.join(self.tmp_dir, "profiles", user["username"])
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, "CV-plaintext.txt"), "w", encoding="utf-8") as f:
            f.write("Alex Muster\nDeveloper")

        mock_gen_letter.return_value = "// Tailored Typst Letter\n= Letter Content"
        mock_compile_typst.return_value = {"success": True}

        with mock.patch("server.finalize_job_documents", return_value={"success": True}):
            err = server._try_generate_letter_pdf(job_id, "test-model", "", user, engine="typst")
        self.assertIsNone(err)
        self.assertTrue(mock_gen_letter.called)
        self.assertTrue(mock_compile_typst.called)


if __name__ == "__main__":
    unittest.main()
