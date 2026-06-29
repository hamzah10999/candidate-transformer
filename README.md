# Multi-Source Candidate Data Transformer

Reads candidate records from four source types — recruiter CSV, ATS JSON, GitHub
profile fixture, and recruiter notes text — deduplicates and merges them into one
canonical profile per candidate, and emits a projected JSON output configured by a
field-spec file. Every emitted value carries a confidence score and source provenance;
unparseable or contested values degrade to `null` rather than being guessed.

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install setuptools             # required for editable install on Python 3.13
pip install -e ".[dev]"            # CLI + tests
pip install -e ".[dev,web]"        # also installs FastAPI UI dependencies
```

Requires Python 3.11+.

---

## Web UI

```bash
uvicorn candidate_transformer.ui:app --reload
# open http://localhost:8000
```

Single-page interface: upload up to 4 source files, pick a config (default or
custom), click **Run Pipeline**. Results show candidate count, merge/review
breakdown, confidence range, and the full projected JSON output.

---

## Run

```bash
# Full output — all fields, confidence + provenance attached
python -m candidate_transformer \
  --sources data/samples/recruiter.csv \
            data/samples/ats.json \
            data/samples/github_fixture.json \
            data/samples/notes.txt \
  --config  data/configs/default.json \
  --output  data/output/default_output.json

# Compact recruiter view — assignment-spec format
python -m candidate_transformer \
  --sources data/samples/recruiter.csv \
            data/samples/ats.json \
            data/samples/github_fixture.json \
            data/samples/notes.txt \
  --config  data/configs/custom.json \
  --output  data/output/custom_output.json
```

Both output files are committed to `data/output/` so you can inspect expected
results without running the pipeline.

---

## Run tests

```bash
pytest
```

191 tests covering normalizers, adapters, merge engine, projection engine, and a
CLI end-to-end smoke test.

---

## Sources supported

| Extension | Detected as | Adapter |
|-----------|-------------|---------|
| `.csv` | Recruiter spreadsheet | `adapters/csv_adapter.py` |
| `.json` with `"login"` key | GitHub profile fixture | `adapters/github_adapter.py` |
| `.json` without `"login"` | ATS export | `adapters/ats_adapter.py` |
| `.txt` | Recruiter notes | `adapters/notes_adapter.py` |

**Adding a new source type:**

1. Create `src/candidate_transformer/adapters/my_adapter.py` with a function
   `extract_my(content: str) -> list[list[Fragment]]`. Each inner list is one
   candidate's fragments; each `Fragment` must have a non-empty `candidate_hint`
   (email → phone → `content_hint(SOURCE, raw_bytes)`).
2. Wire it into `__main__.py` `_detect_and_extract()`.
3. Add tests in `tests/adapters/`.

No other files need to change — the merge and projection stages operate on
`Fragment` objects regardless of origin.

---

## Design decisions

- **Fragment-first, normalise-late.** Adapters emit raw `Fragment` objects
  without parsing phone numbers or dates. Normalizers run centrally in the merge
  stage so the same logic applies regardless of which source a value came from.
  This makes adapters trivially testable and keeps parsing bugs in one place.

- **Noisy-OR confidence with disagreement penalty.** When multiple sources agree
  on a value, confidence compounds: `1 − ∏(1 − trust_i)`. When they disagree
  (e.g. CSV says "Software Engineer", ATS says "Senior Software Engineer"), the
  winning value's confidence is multiplied by 0.8 per extra unique value seen.
  Source trust: ATS = CSV = 0.9, GitHub = 0.7, notes = 0.5.

- **Hashed blocking, not all-pairs.** Candidates are clustered by exact email
  match first, then by E.164 phone. A recycled-phone guard prevents two clusters
  with *different* confirmed email sets from being merged on a phone alone — they
  are flagged `NEEDS_REVIEW` instead. Name-only matching is explicitly excluded
  (too many false positives at scale).

- **Phone retry pass.** Bare national numbers (e.g. `4085559876` with no country
  code) fail at extract time. The merge stage retries them once a country is
  resolved from another source in the same cluster, enabling cross-source
  reasoning. In the sample data, Bob's CSV phone `4085559876` resolves to
  `+14085559876` using the US country inferred from his ATS record.

---

## Assumptions and deliberately descoped items

- **GitHub via fixture, not live API.** The adapter reads a JSON file in the
  same schema as the GitHub Users API. Making live calls would require OAuth
  token management, rate-limit handling, and non-deterministic test fixtures —
  all out of scope for a take-home assignment.

- **No fuzzy name matching.** "Roberto Martinez" in the notes file and "Bob
  Martinez" in the CSV are *not* merged — they only link because both records
  carry `bob.martinez@email.com`. Fuzzy name matching produces too many false
  positives in a global candidate pool and is deliberately excluded.

- **No ML resume extraction.** Notes parsing uses regex over labelled fields
  (`Title:`, `Skills:`, email addresses). A production system might use an NER
  model, but the regex approach is fully deterministic, debuggable, and sufficient
  for structured recruiter notes.

- **No LinkedIn / resume PDF ingestion.** Adding a LinkedIn adapter would follow
  the same pattern as the existing adapters (implement `extract_linkedin()`,
  return `list[list[Fragment]]`, wire into the CLI). The merge and projection
  stages need no changes.

- **Single-pass skill canonicalization.** The skill alias map (`normalizers/skill.py`)
  covers common synonyms (JS → JavaScript, etc.). Unknown skills are accepted
  verbatim at 0.5 confidence. A production system would use a curated taxonomy
  or an embedding-based matcher.
