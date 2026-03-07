# Devin Session Metadata Extraction

## Overview
Extracted on: 2026-03-07T13:13:19.695974
Total sessions found: 20
Sessions processed (with content): 19

## Output Files

### Per-Session Metadata
- `sessions_raw.json` - Raw session list from API
- `sessions_metadata.json` - Extracted structured metadata for each session

### Aggregated Analysis
- `user_profile.json` - User profile (preferences, tech stack, conventions, patterns)
- `apps_catalog.json` - Catalog of 18 identified apps/projects
- `decisions_log.json` - Chronological log of 55 technical decisions
- `corrections_log.json` - Log of 33 user corrections/rejections

## Schema

### Session Metadata (sessions_metadata.json)
```json
{
  "session_id": "...",
  "date": "...",
  "title": "...",
  "project": "name of app/project",
  "goals": ["session goals"],
  "decisions": ["technical decisions made"],
  "corrections": ["user corrections/rejections"],
  "preferences": ["expressed preferences"],
  "outcome": "success|partial|failed",
  "outcome_detail": "what was achieved",
  "tech_stack": ["technologies used"],
  "app_requirements": ["requirements defined"],
  "patterns": ["behavioral patterns"]
}
```

## AutoLauncher Integration Proposal

### Recommended Data Model Changes

The existing AutoLauncher backend (FastAPI + SQLite) could integrate this metadata by adding:

1. **SessionMetadata table** - stores per-session extracted data
   - Links to existing App model via project name
   - Enables querying decisions/corrections per app

2. **UserProfile table** - stores aggregated user preferences
   - Preferred tech stack, conventions, architectural patterns
   - Used by AI to personalize app generation

3. **DecisionLog table** - chronological decision tracking
   - Indexed by date and project
   - Enables learning from past decisions

4. **AppEnrichment** - extend existing App model with:
   - `devin_sessions` - list of related session IDs
   - `extracted_requirements` - requirements from session analysis
   - `tech_stack_detected` - auto-detected tech stack

### Integration Endpoints (proposed)
- `POST /api/metadata/import` - import extracted JSON files
- `GET /api/metadata/profile` - get user profile for AI context
- `GET /api/metadata/app/{app_name}/decisions` - get decisions for an app
- `GET /api/metadata/search` - search across all metadata

### Implementation Priority
1. Import pipeline (read JSON files into DB)
2. User profile endpoint (for AI context injection)
3. App enrichment (link sessions to apps)
4. Search and query capabilities

**NOTE: This is a proposal only. Implementation will be done in a separate step.**
