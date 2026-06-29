# Multi-Source Candidate Data Transformer

Ingests messy candidate data from four source types — recruiter CSV, ATS JSON,
GitHub profile JSON, recruiter notes TXT — and produces one canonical JSON
profile per candidate with field-level confidence scores and provenance tracking.

**Core design rule:** wrong-but-confident is worse than honestly-empty.
Unparseable or contested values degrade to `null` with low confidence rather than
being guessed.

---

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

---

## Running

```bash
python -m candidate_transformer \
  --sources data/samples/recruiter.csv \
            data/samples/ats.json \
            data/samples/github_fixture.json \
            data/samples/notes.txt \
  --config  data/configs/default.json \
  --output  data/output/result.json
```

The CLI prints a per-source extraction count and a summary to stdout; the
output JSON is written to `--output`.

### Source type detection

| Extension | Detected as |
|-----------|-------------|
| `.csv`    | Recruiter CSV |
| `.txt`    | Recruiter notes |
| `.json` with `"login"` key | GitHub profile fixture |
| `.json` without `"login"` | ATS JSON |

Multiple source files of the same type are accepted; pass them all to
`--sources`.

---

## Sample data

| File | Contents |
|------|----------|
| `data/samples/recruiter.csv` | 5 rows; Alice, two Bobs (different emails), Carol, Dana |
| `data/samples/ats.json` | 3 records: Alice, Bob (b.ramirez), Eve |
| `data/samples/github_fixture.json` | 2 profiles: Alice and Eve (no email for Eve) |
| `data/samples/notes.txt` | Two paragraphs: Carol and Bob (bob@ramirez.dev) |

---

## Config files

### `data/configs/default.json`

Full canonical output: all fields, E.164 phones, confidence/provenance off,
`on_missing: "null"` (absent fields appear as JSON `null`).

### `data/configs/custom.json`

Compact recruiter view: name, primary email, phone in NATIONAL format,
skills list. `include_confidence: true` attaches `_confidence` for
`FieldValue`-backed fields. `on_missing: "omit"` drops absent keys entirely.

---

## Sample output walkthrough

Running the full sample produces 7 canonical profiles:

| Candidate | merge_state | Notable |
|-----------|-------------|---------|
| Alice Müller | `merged` | Merged across CSV + ATS + GitHub; title taken from ATS (higher source trust than CSV) |
| Bob Ramirez `bob@ramirez.dev` | `merged` | CSV + notes paragraph; no phone link to other Bob cluster |
| Carol Singh | `merged` | CSV + notes; bare 10-digit phone in CSV resolved after country inferred from notes phone |
| Bob Ramirez `b.ramirez@work.com` | `merged` | CSV + ATS |
| Dana Kim | `single` | CSV only; Korean phone parsed correctly |
| Eve Nakamura `eve@nakamura.jp` | `single` | ATS only; no link to GitHub record below |
| Eve Nakamura (GitHub) | `single` | GitHub fixture has no email — content-hash hint, not merged with ATS Eve |

Bob Ramirez appears **twice** intentionally: the two email addresses
(`bob@ramirez.dev` and `b.ramirez@work.com`) share no phone link, so
name-only matching is explicitly rejected. A human reviewer can inspect
both records and merge manually if needed.

---

## Architecture

```
adapters/          extract raw Fragments from each source type
  csv_adapter      DictReader → one Fragment group per row
  ats_adapter      JSON → one Fragment group per candidate object
  github_adapter   GitHub profile + repo languages → Fragment group
  notes_adapter    Regex over each blank-line paragraph → Fragment group
  _hint.py         SHA-256(source:raw) for identity-free fragments

normalizers/       pure functions, never guess
  phone.py         libphonenumber → ParsedPhone or (None, reason)
  date.py          dateutil → ParsedDate; season stripped, month never invented
  country.py       alias map → ISO 3166-1 alpha-2; empty-string guard
  skill.py         alias map → canonical name; verbatim fallback at 0.5 confidence

merge/
  _union_find.py   path-compressed, union-by-rank UnionFind
  _resolve.py      noisy-OR confidence; disagreement penalty 0.8×; phone retry
  engine.py        email blocking → phone blocking (recycled-phone guard) →
                   one CandidateProfile per cluster

projection/
  _paths.py        resolve_path: simple / indexed [N] / wildcard []
  _schema.py       derive_schema: JSON Schema Draft-7 from ProjectionConfig
  engine.py        project(): path resolve → normalize override → on_missing →
                   _confidence/_provenance attach → schema validate

models/
  fragment.py      Fragment + Provenance
  canonical.py     CandidateProfile + FieldValue[T] + ParsedPhone + ParsedDate
  config.py        ProjectionConfig + FieldSpec + GlobalConfig

__main__.py        CLI: detect sources → extract → merge → project → write
```

### Confidence model

Source trust: ATS = CSV = 0.9 · GitHub = 0.7 · notes = 0.5.

Per-field confidence: `noisy_OR(trust values) × disagreement_penalty^(n_unique_values - 1)`,
where disagreement_penalty = 0.8. A field seen in two sources that agree
gets higher confidence than a field from only one source; a contested field
is penalised.

`NEEDS_REVIEW` is set when two clusters with different confirmed email addresses
share a phone number (recycled/reassigned number). Overall confidence for
`NEEDS_REVIEW` profiles is capped at 0.4.

---

## Assumptions

- **Phone without country code**: bare national numbers (e.g. `4155559999`) are
  stored as unresolved fragments and retried during the merge phase once a
  country code is inferred from another source for the same candidate.
- **GitHub via fixture**: the GitHub adapter reads a JSON fixture in the same
  schema as the GitHub Users API response. It does not make live network
  requests; swap the fixture file to test with real data.
- **Notes are one candidate per paragraph**: blank lines separate candidates.
  If a single paragraph mentions multiple people (unusual for structured notes),
  the first email found becomes the grouping key and all fragments in that
  paragraph are attributed to that candidate.
- **Skill aliases**: a small built-in alias map handles common synonyms
  (e.g. `JS → JavaScript`). Unknown skills are passed through verbatim at
  0.5 confidence.
- **Date normalization**: seasons are stripped (`Summer 2021 → 2021`); a bare
  year stays as year-only — no month is invented.

---

## Descoped / known limitations

- **No live GitHub API calls**: would require OAuth token management and
  rate-limit handling. The fixture format matches the real API exactly, so
  a thin wrapper is all that's needed.
- **No deduplication of the two Bob Ramirez clusters**: name-only matching
  is explicitly excluded (high false-positive risk). A human review step or
  a richer identifier (LinkedIn URL, employee ID) would close this gap.
- **Eve Nakamura GitHub record not merged with ATS Eve**: the GitHub fixture
  for `eve-nakamura` has `"email": null`. Without a shared email or phone
  there is no strong merge signal. The `github_url` field on the ATS Eve
  record would allow matching, but URL-to-login resolution is not
  implemented to avoid false positives from forks or username changes.
- **Notes adapter**: regex extraction is fragile against unusual formatting.
  A structured note template (with labeled fields) dramatically improves
  extraction quality.
- **No job history / date ranges**: `DateRange` and work-history arrays are
  defined in the model but no source currently emits them. Adding a source
  that does (e.g., a LinkedIn export) requires only a new adapter.

---

## Tests

```bash
pytest
```

191 tests covering all normalizers, adapters, merge logic (Union-Find,
recycled-phone guard, confidence calculations), projection engine, and CLI
end-to-end smoke test.
