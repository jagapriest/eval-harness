List every company, organization, or named commercial entity that appears anywhere in
the document below — regardless of the role it plays.

Include entities named as any of the following:

- competitors
- customers or clients
- suppliers, vendors, or manufacturing partners
- channel, delivery, or implementation partners
- analyst firms, auditors, rating agencies, or research houses
- acquirers, acquisitions, subsidiaries, or joint ventures
- regulators, standards bodies, and industry consortia
- the filer itself, and any parent or affiliate

Do NOT include:

- unnamed categories ("large enterprise software companies", "system integrators")
- product or service names, unless they are also the company name
- geographic regions, market segments, or job titles

For each entity give its `role` as one of:
`competitor`, `customer`, `supplier`, `partner`, `analyst`, `self`, `other`.

Use the role the **document** assigns it. If the document is ambiguous about the role,
use `other`.

Return only JSON:

```json
{
  "entities": [
    {"name": "string, as written in the document", "role": "competitor|customer|supplier|partner|analyst|self|other"}
  ],
  "summary": "One sentence on what kinds of organizations this document names."
}
```

DOCUMENT:
{{DOCUMENT}}
