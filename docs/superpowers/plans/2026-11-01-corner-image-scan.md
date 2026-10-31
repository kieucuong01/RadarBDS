# Scan corner coordinates from a document image

Use the existing coordinate/corner flow. Browser-only WebAssembly OCR would
require a CSP change; use the already installed Tesseract 5 native CLI instead.
Only a user-selected crop is sent to the same-origin RadarBDS endpoint. Decode,
normalize and OCR in memory without retaining images or forwarding to a provider.

1. Add bounded raster-only OCR service and POST route beside `corners.json`.
   One OCR process per worker, one native thread, timeout, size/pixel caps;
   fixed CLI arguments with stdin/stdout, no shell and no owner/identity output.
   Parse only plausible ordered coordinate pairs, never silently replace letters.
2. Add a separate scanner module under Góc ranh: local image preview, crop by
   drag, rotate, loading/cancel, editable draft and explicit review confirmation.
   Apply copies reviewed numbers into existing corner input; drawing stays manual.
   Dispose/abort on close, source-system change, new file and Maps teardown.
3. Test parser, bad images, size limits, busy/timeout, command safety and route
   privacy. Test scanner lifecycle and review gate, then exercise real OCR using
   a synthetic coordinate table (no actual title deed or personal information).
4. Commit only this feature, push the previous coordinate commit plus scan work,
   wait for CI, preserve exact unrelated VPS edits, deploy and restore them.
   Verify public UI including OCR, correction, application and corner drawing.

Photos are not cadastral evidence. Explain that OCR digits must be checked and
that VN-2000 still needs the correct projection from the document.
