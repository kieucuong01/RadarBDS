"""Build source-sheet previews, without assigning unverified geographic coordinates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    import pypdfium2 as pdfium
    directory = ROOT / '.local/planning-ben-cat'
    catalog = json.loads((ROOT / 'config/ben_cat_planning_catalog.json').read_text(encoding='utf8'))
    artifacts = {}
    for layer in catalog['layers']:
        if layer['status'] != 'document_only':
            continue
        folder = directory / layer['slug']
        pdf_path = folder / 'original.pdf'
        if hashlib.sha256(pdf_path.read_bytes()).hexdigest() != layer['source_sha256']:
            raise ValueError('Source PDF hash mismatch: ' + layer['slug'])
        document = pdfium.PdfDocument(pdf_path)
        page = document[layer['page'] - 1]
        path = folder / 'preview.webp'
        page.render(scale=1.5).to_pil().save(path, quality=92)
        artifacts[layer['id']] = hashlib.sha256(path.read_bytes()).hexdigest()
        print(layer['slug'], path.stat().st_size, flush=True)
        page.close()
        document.close()
    (directory / 'documents.json').write_text(json.dumps(artifacts, indent=2), encoding='utf8')


if __name__ == '__main__':
    build()
