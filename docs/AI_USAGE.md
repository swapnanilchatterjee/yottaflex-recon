# AI Usage & Collaboration Disclosure

In accordance with the YottaFlex AI Submission Guidelines, this document transparently discloses how AI tools were used during the design, implementation, and verification of this project.

---

## 1. Tools Used
- **Primary Coding Agent:** Antigravity CLI (powered by Google Gemini 3.8 Flash).
- **Session Prompt Log:** `prompts/PROMPT_HISTORY.md` (all user commands recorded verbatim with timestamps).

---

## 2. Where AI Accelerated the Project
- **Scaffolding & Boilerplate:** Creating standard project skeleton (`Makefile`, `pyproject.toml`, directory trees).
- **Data Generation Rules:** Drafting synthetic data generator arrays with diverse boundary dates, currencies, and test amounts.
- **Test Skeleton Generation:** Generating pytest fixtures and repetitive parameter variations for negative validation rules.
- **Documentation Structuring:** Formatting markdown tables, ASCII diagrams, and report schemas.

---

## 3. What I Personally Reviewed, Validated & Changed
- **Deduplication Logic:** Ensured the deduplication tie-breaker explicitly favors the last occurrence in the file when `updated_at` timestamps are identical, matching stream processing out-of-order semantics.
- **Financial Precision:** Switched floating-point rounding to `decimal.Decimal` with `ROUND_HALF_UP` to prevent off-by-a-penny accounting discrepancies.
- **Line Number Traceability:** In the CSV reader, ensured line numbers reflect 1-based physical file row numbers (including headers) so that quarantine error reports map directly to row numbers in text editors.
- **Mutation Testing:** Manually corrupted sample CSV records (modifying amounts, deleting rows, injecting duplicates) and confirmed the reconciliation tool fails immediately with exit code 1.
- **Benchmark Realism:** Ran the actual 100k benchmark and verified that numbers in `docs/PERFORMANCE.md` matched real stdout timings from the Windows shell.

---

## 4. Notable Edge Cases Caught & Corrected
1. **Pandas NaN Type Coercion:** Pandas converts empty string cells in numeric/string columns to `NaN` floats by default. Fixed by specifying `dtype=str` and chaining `.fillna("")` to ensure exact string comparisons.
2. **Target Outer Join Cartesian Risk:** If the target dataset had duplicate keys, an un-deduplicated merge could cause a combinatorial row explosion. Fixed by isolating duplicate target keys first, deduplicating before the field merge, and isolating duplicate keys in `mismatches/duplicate_in_target.csv`.

---

## 5. Verification Command
To reproduce the automated test and reconciliation evidence independently:
```bash
make test
make demo
```
