# Checkpoint: Answer Evidence Qualification

**Date:** 2026-09-27  
**Status:** Implemented and verified

## Problem

- HIGH-disclosure responses could describe organizational activity despite releasing no message records.
- MEDIUM responses could present a capped retrieval (up to three records) as if it represented all matching records.
- The deterministic offline fallback did not consistently apply either evidence limitation.

## Changes

- Updated `backend/aegis/llm.py` prompts to prohibit unsupported HIGH-tier details and to identify MEDIUM records as a limited sample.
- Changed the offline HIGH response to a generic, evidence-aware statement that does not derive claims from topic hints.
- Qualified offline MEDIUM responses as sample-based and potentially incomplete.
- Hardened `sanitize_high_answer()` in `backend/aegis/moderation.py`: when zero records are disclosed, it replaces the generated response with a generic statement and sets confidence to `0.20`.
- Extended `sanitize_medium_answer()` to redact sensitive content and ensure answers with retrieved records state that the sample is not exhaustive and more matches may exist.
- Wired disclosed-record counts into both sanitizers in `backend/server.py`.
- Added regression tests for offline HIGH/MEDIUM behavior and both answer sanitizers.

## Files

- `backend/aegis/llm.py`
- `backend/aegis/moderation.py`
- `backend/server.py`
- `backend/tests/test_llm_provenance.py`
- `backend/tests/test_moderation_disclosure.py`

## Verification

- Targeted disclosure/LLM tests: **14 passed**.
- Full backend test suite: **86 passed** (`pytest tests/ -n 0`).
- Frontend development server compiled successfully at `http://localhost:3000`.
- Backend health returned HTTP 200 at `http://127.0.0.1:8001/api/health`, reporting MongoDB connected and Neo4j-only retrieval.
- Neo4j Bolt/HTTP and MongoDB listeners remained available.

## Expected behavior

- **HIGH, zero disclosed records:** Generic privacy statement only; no ungrounded topics, departments, or activities.
- **MEDIUM, records disclosed:** Redacted evidence accompanied by a clear note that the retrieved sample is not exhaustive.
