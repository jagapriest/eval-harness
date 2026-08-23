You are a research analyst. Read the market document below and identify the competitors named in it.

Return JSON with this structure:
{
  "competitors": [
    {"name": "...", "evidence": "...", "confidence": "high|medium|low"}
  ],
  "summary": "2-3 sentences on the competitive landscape"
}

The "evidence" field must be a verbatim span from the document of 25 words or fewer.
Return only JSON.

DOCUMENT:
{{DOCUMENT}}
