# Radar BDS Marketing Loop State

This folder stores durable state and append-only run logs for Radar BDS marketing
loops. Do not keep scheduled-loop memory only in chat or automation prompts.

Rules:

- One loop owns one state/log pair.
- Do not store raw PII, phone numbers, original listing URLs, or secrets.
- Use stable dedupe keys such as URL path, slug, primary keyword, or internal IDs.
- A blocked run still gets logged with `acted=0` and a short blocker.
- If a loop starts producing repeated low-value work, fix or disable the loop.

Current loops:

| Loop | State/log |
|---|---|
| Daily SEO publisher | `.agents/seo-publish-history.md` and `.agents/loops/daily-seo-publisher.log` |
