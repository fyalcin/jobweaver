"""Rebuild fictional demo PDFs and previews with installed LaTeX and Poppler tools. No AI calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import career_record
import career_cv
import reviewed_documents
from document_artifacts import validate_pdf


def main():
    record_path = ROOT / "examples" / "career_record.example.yaml"
    problems = [p for p in career_record.check(record_path) if not p.warning]
    if problems:
        raise ValueError(str(problems))
    record, _ = career_record.load(record_path)
    text = record_path.read_text()
    jobs = json.loads((ROOT / "examples" / "demo" / "jobs.json").read_text())
    claims = {c["id"]: c for entry in record["entries"] for c in entry["claims"]}
    for job in jobs[:3]:
        family = "data-engineering" if job["id"] == "demo_02" else "research-software"
        selected = ["weather-lab-pipeline", "weather-lab-checker", "rainfall-author"]
        letter = {"date": "22 October 2026", "language": "en", "content": {
            "salutation": "Dear hiring team,",
            "paragraphs": [
                {"text": f"I am applying for the {job['title']} role at {job['company']}. The work you describe connects with my experience preparing climate datasets for research.", "facts": []},
                {"text": "At the Institute for Weather Studies, I wrote Python scripts that convert 40 TB of model output into analysis-ready NetCDF files. I also adapted an existing quality-control tool to flag corrupted model runs before analysis. These examples show the data preparation and checking work I could discuss with your team.", "facts": selected[:2]},
                {"text": "I am the main developer of rainfall-stats, a Python package released on PyPI with three releases. I would welcome the chance to discuss how this work relates to your team’s needs.", "facts": selected[2:]},
            ], "closing": "Kind regards,"}}
        store = reviewed_documents.record_store(record, text, family)
        output = ROOT / "examples" / "demo" / "documents" / job["id"]
        output.mkdir(parents=True, exist_ok=True)
        # The short example record fits on one page. The normal renderer retains its two-page layout.
        compact_cv = career_cv.render(record, family).replace(r'\newpage', r'\vspace{8pt}')
        sources = {"cv": compact_cv,
                   "cl": reviewed_documents.render_letter(store, letter, "latex", job)}
        # All evidence is fictional. Never describe these as live model/verifier output.
        (output / "evidence.json").write_text(json.dumps({"provenance": "hand-prepared fictional example",
            "claims": [{"id": key, "text": claims[key]["text"]} for key in selected]}, indent=2) + "\n")
        for kind, source in sources.items():
            (output / f"{kind}.tex").write_text(source)
            with tempfile.TemporaryDirectory(prefix="jobweaver-demo-pdf-") as temp:
                path = Path(temp) / f"{kind}.tex"
                path.write_text(source)
                result = subprocess.run(["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", str(path)],
                                        cwd=temp, capture_output=True, timeout=45)
                if result.returncode:
                    raise RuntimeError(result.stdout.decode(errors="replace")[-2500:])
                pdf = Path(temp) / f"{kind}.pdf"
                validate_pdf(pdf)
                (output / f"{kind}.pdf").write_bytes(pdf.read_bytes())
                for preview in output.glob(f"{kind}-*.png"):
                    preview.unlink()
                subprocess.run(["pdftoppm", "-r", "100", "-png", str(pdf), str(output / kind)], check=True, capture_output=True)
        print(f"Prepared {job['id']}: {job['company']}")


if __name__ == "__main__":
    main()
