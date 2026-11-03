# AI Prompt History

Record of all prompts issued to the AI coding agent during development, as required by the YottaFlex AI Submission Guidelines.

---

### Prompt 0 — Initial Kickoff & Strategy Formulation
**Timestamp:** `2026-11-03T07:40:00+05:30`
**Prompt:**
```
Read PLAN.md fully, plus yotta_direct.txt. Summarise back to me the goal, stack, and the 13 phases. Understand the rules, architecture, count equation, and test matrix.
```
**Outcome:**
Read problem statement and candidate guidelines; verified constraints (Python 3.10+, pandas, numpy, pytest, standard library). Structured 13-phase engineering plan.

---

### Prompt 1 — Complete Build, Testing, QA Report, Git Push & Cleanup
**Timestamp:** `2026-11-03T07:44:54+05:30`
**Prompt:**
```
read the plan read understand build it after then u have github access psuh to repo with good readme before pushing check which files should be in gitignore also test it like a qa tester and give report that too in readme then push the after that clear in localto release space also make a md file ffor me too which u put it on gitignore it is for before interview what and how the project is for understanding
```
**Outcome:**
- Scaffold project layout, schemas, config, and run log.
- Implement resilient CSV ingestion with malformed quarantine.
- Implement validation, business key dedup, and foreign key verification.
- Implement deterministic transform with Decimal HALF_UP currency rounding.
- Implement atomic, idempotent publisher with `updated_at` stale guard.
- Implement 4-tier reconciliation engine (counts, keys, aggregates, field-level) with machine-readable JSON & isolated CSVs.
- Implement seeded reproducible data generator with labelled defect injection.
- Implement CLI with manifest recording.
- Run complete QA test suite across 35+ test scenarios.
- Benchmark vectorised vs row-loop comparisons.
- Draft comprehensive README with architecture, data dictionary, run instructions, and QA Test Report.
- Create candidate interview guide `INTERVIEW_PREP.md` (gitignored).
- Push cleanly to GitHub public repository.
- Release local temporary storage and build caches.
