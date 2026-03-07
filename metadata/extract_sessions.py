#!/usr/bin/env python3
"""
Devin Session Metadata Extractor
Extracts structured metadata from all Devin sessions via API,
then creates aggregated analysis files for AutoLauncher integration.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime
from openai import OpenAI

# --- Config ---
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY")
OPENAI_API_KEY = os.environ.get("Open_AI_K6")
OUTPUT_DIR = "/home/ubuntu/autolauncher-pro/metadata"
DEVIN_API_BASE = "https://api.devin.ai/v1"

if not DEVIN_API_KEY:
    print("ERROR: DEVIN_API_KEY not set")
    sys.exit(1)
if not OPENAI_API_KEY:
    print("ERROR: Open_AI_K6 not set")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)

headers = {"Authorization": f"Bearer {DEVIN_API_KEY}"}
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def fetch_all_sessions():
    """Fetch all sessions with pagination."""
    all_sessions = []
    offset = 0
    limit = 100
    while True:
        print(f"  Fetching sessions offset={offset}...")
        resp = requests.get(
            f"{DEVIN_API_BASE}/sessions",
            headers=headers,
            params={"limit": limit, "offset": offset}
        )
        if resp.status_code != 200:
            print(f"  ERROR {resp.status_code}: {resp.text}")
            break
        data = resp.json()
        sessions = data.get("sessions", [])
        if not sessions:
            break
        all_sessions.extend(sessions)
        print(f"  Got {len(sessions)} sessions (total: {len(all_sessions)})")
        if len(sessions) < limit:
            break
        offset += limit
        time.sleep(0.3)
    return all_sessions


def fetch_session_detail(session_id):
    """Fetch full session detail including messages."""
    resp = requests.get(
        f"{DEVIN_API_BASE}/sessions/{session_id}",
        headers=headers
    )
    if resp.status_code != 200:
        print(f"  ERROR fetching {session_id}: {resp.status_code}")
        return None
    return resp.json()


def build_conversation_text(messages):
    """Build readable conversation text from messages."""
    lines = []
    for msg in messages:
        origin = msg.get("origin", msg.get("type", "unknown"))
        text = msg.get("message", "")
        if text:
            # Truncate very long messages
            if len(text) > 2000:
                text = text[:2000] + "... [truncated]"
            lines.append(f"[{origin}]: {text}")
    return "\n".join(lines)


def extract_metadata_with_llm(session_summary, conversation_text):
    """Use OpenAI to extract structured metadata from conversation."""
    prompt = f"""Analyze this Devin AI coding session and extract structured metadata.

Session info:
- ID: {session_summary.get('session_id', 'unknown')}
- Title: {session_summary.get('title', 'unknown')}
- Created: {session_summary.get('created_at', 'unknown')}
- Status: {session_summary.get('status_enum', session_summary.get('status', 'unknown'))}
- PR: {json.dumps(session_summary.get('pull_request'))}

Conversation (may be truncated):
{conversation_text[:12000]}

Extract the following as JSON (use empty arrays/strings if info not available):
{{
  "project": "name of the app/project being worked on",
  "goals": ["what were the goals of this session"],
  "decisions": ["what architectural/technical decisions were made"],
  "corrections": ["what did the user correct/reject and why"],
  "preferences": ["user preferences expressed - tech stack, style, conventions"],
  "outcome": "success|partial|failed",
  "outcome_detail": "what was achieved and what wasn't",
  "tech_stack": ["technologies used"],
  "app_requirements": ["app requirements if defined"],
  "patterns": ["recurring patterns in user behavior"]
}}

Return ONLY valid JSON, no markdown formatting."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000
        )
        text = response.choices[0].message.content.strip()
        # Remove markdown code block if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)
    except Exception as e:
        print(f"  LLM extraction error: {e}")
        return {
            "project": "unknown",
            "goals": [],
            "decisions": [],
            "corrections": [],
            "preferences": [],
            "outcome": "unknown",
            "outcome_detail": "",
            "tech_stack": [],
            "app_requirements": [],
            "patterns": []
        }


def create_aggregated_files(all_metadata):
    """Create aggregated analysis files from all session metadata."""

    # --- user_profile.json ---
    profile_prompt = f"""Based on these {len(all_metadata)} Devin session metadata entries, create a comprehensive user profile.

Sessions data (summarized):
{json.dumps([{
    'project': m.get('project'),
    'preferences': m.get('preferences'),
    'corrections': m.get('corrections'),
    'tech_stack': m.get('tech_stack'),
    'patterns': m.get('patterns'),
    'outcome': m.get('outcome')
} for m in all_metadata], indent=2)[:15000]}

Create a JSON profile:
{{
  "preferred_tech_stack": ["ranked list of preferred technologies"],
  "coding_conventions": ["coding conventions and standards"],
  "architectural_preferences": ["architectural preferences and patterns"],
  "communication_style": "how the user communicates and works",
  "frustrations": ["what frustrates the user / what doesn't work"],
  "what_works_well": ["what worked well"],
  "work_patterns": ["general work patterns"],
  "key_principles": ["key principles the user follows"]
}}

Return ONLY valid JSON."""

    print("Creating user_profile.json...")
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": profile_prompt}],
            temperature=0.2,
            max_tokens=3000
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        user_profile = json.loads(text)
    except Exception as e:
        print(f"  Error creating user profile: {e}")
        user_profile = {"error": str(e)}

    with open(os.path.join(OUTPUT_DIR, "user_profile.json"), "w") as f:
        json.dump(user_profile, f, indent=2, ensure_ascii=False)

    # --- apps_catalog.json ---
    projects = {}
    for m in all_metadata:
        proj = m.get("project", "unknown")
        if proj and proj != "unknown":
            if proj not in projects:
                projects[proj] = {
                    "name": proj,
                    "sessions": [],
                    "tech_stack": set(),
                    "requirements": [],
                    "goals": [],
                    "outcomes": []
                }
            projects[proj]["sessions"].append(m.get("session_id", ""))
            projects[proj]["tech_stack"].update(m.get("tech_stack", []))
            projects[proj]["requirements"].extend(m.get("app_requirements", []))
            projects[proj]["goals"].extend(m.get("goals", []))
            projects[proj]["outcomes"].append(m.get("outcome", "unknown"))

    apps_catalog = []
    for name, data in projects.items():
        # Determine status from outcomes
        outcomes = data["outcomes"]
        if all(o == "success" for o in outcomes):
            status = "deployed"
        elif any(o == "success" for o in outcomes):
            status = "in-progress"
        elif any(o == "partial" for o in outcomes):
            status = "in-progress"
        else:
            status = "planned"

        apps_catalog.append({
            "name": name,
            "description": "; ".join(list(set(data["goals"]))[:5]),
            "status": status,
            "tech_stack": sorted(list(data["tech_stack"])),
            "requirements": list(set(data["requirements"]))[:20],
            "related_sessions": data["sessions"],
            "session_count": len(data["sessions"]),
            "priority": "high" if len(data["sessions"]) > 3 else "medium" if len(data["sessions"]) > 1 else "low"
        })

    apps_catalog.sort(key=lambda x: x["session_count"], reverse=True)

    print(f"Creating apps_catalog.json ({len(apps_catalog)} apps)...")
    with open(os.path.join(OUTPUT_DIR, "apps_catalog.json"), "w") as f:
        json.dump(apps_catalog, f, indent=2, ensure_ascii=False)

    # --- decisions_log.json ---
    decisions_log = []
    for m in all_metadata:
        for decision in m.get("decisions", []):
            if decision:
                decisions_log.append({
                    "date": m.get("date", ""),
                    "session_id": m.get("session_id", ""),
                    "project": m.get("project", "unknown"),
                    "decision": decision,
                    "context": m.get("outcome_detail", "")
                })

    decisions_log.sort(key=lambda x: x.get("date", ""))
    print(f"Creating decisions_log.json ({len(decisions_log)} decisions)...")
    with open(os.path.join(OUTPUT_DIR, "decisions_log.json"), "w") as f:
        json.dump(decisions_log, f, indent=2, ensure_ascii=False)

    # --- corrections_log.json ---
    corrections_log = []
    for m in all_metadata:
        for correction in m.get("corrections", []):
            if correction:
                corrections_log.append({
                    "date": m.get("date", ""),
                    "session_id": m.get("session_id", ""),
                    "project": m.get("project", "unknown"),
                    "correction": correction
                })

    corrections_log.sort(key=lambda x: x.get("date", ""))
    print(f"Creating corrections_log.json ({len(corrections_log)} corrections)...")
    with open(os.path.join(OUTPUT_DIR, "corrections_log.json"), "w") as f:
        json.dump(corrections_log, f, indent=2, ensure_ascii=False)

    return user_profile, apps_catalog, decisions_log, corrections_log


def create_readme(total_sessions, processed, apps_count, decisions_count, corrections_count):
    """Create summary README."""
    readme = f"""# Devin Session Metadata Extraction

## Overview
Extracted on: {datetime.now().isoformat()}
Total sessions found: {total_sessions}
Sessions processed (with content): {processed}

## Output Files

### Per-Session Metadata
- `sessions_raw.json` - Raw session list from API
- `sessions_metadata.json` - Extracted structured metadata for each session

### Aggregated Analysis
- `user_profile.json` - User profile (preferences, tech stack, conventions, patterns)
- `apps_catalog.json` - Catalog of {apps_count} identified apps/projects
- `decisions_log.json` - Chronological log of {decisions_count} technical decisions
- `corrections_log.json` - Log of {corrections_count} user corrections/rejections

## Schema

### Session Metadata (sessions_metadata.json)
```json
{{
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
}}
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
- `GET /api/metadata/app/{{app_name}}/decisions` - get decisions for an app
- `GET /api/metadata/search` - search across all metadata

### Implementation Priority
1. Import pipeline (read JSON files into DB)
2. User profile endpoint (for AI context injection)
3. App enrichment (link sessions to apps)
4. Search and query capabilities

**NOTE: This is a proposal only. Implementation will be done in a separate step.**
"""
    with open(os.path.join(OUTPUT_DIR, "README.md"), "w") as f:
        f.write(readme)


def main():
    print("=" * 60)
    print("DEVIN SESSION METADATA EXTRACTOR")
    print("=" * 60)

    # Step 1: Fetch all sessions
    print("\n[1/4] Fetching all sessions...")
    all_sessions = fetch_all_sessions()
    print(f"  Total sessions: {len(all_sessions)}")

    if not all_sessions:
        print("ERROR: No sessions fetched. Check API key.")
        sys.exit(1)

    # Save raw session list
    with open(os.path.join(OUTPUT_DIR, "sessions_raw.json"), "w") as f:
        json.dump(all_sessions, f, indent=2, ensure_ascii=False)

    # Step 2: Fetch details and extract metadata for each session
    print("\n[2/4] Extracting metadata from each session...")
    all_metadata = []
    skipped = 0

    for i, sess in enumerate(all_sessions):
        sid = sess["session_id"]
        title = sess.get("title", "untitled")
        print(f"\n  [{i+1}/{len(all_sessions)}] {sid} - {title}")

        # Fetch full session with messages
        detail = fetch_session_detail(sid)
        if not detail:
            skipped += 1
            continue

        messages = detail.get("messages", [])
        if len(messages) < 2:
            print(f"    Skipping - only {len(messages)} messages")
            skipped += 1
            continue

        conversation = build_conversation_text(messages)
        if len(conversation) < 50:
            print(f"    Skipping - conversation too short")
            skipped += 1
            continue

        # Extract metadata via LLM
        metadata = extract_metadata_with_llm(sess, conversation)
        metadata["session_id"] = sid
        metadata["date"] = sess.get("created_at", "")
        metadata["title"] = title
        metadata["status_enum"] = sess.get("status_enum", "")
        metadata["pull_request"] = sess.get("pull_request")

        all_metadata.append(metadata)
        print(f"    Extracted: project={metadata.get('project', '?')}, outcome={metadata.get('outcome', '?')}")

        # Rate limiting
        time.sleep(0.5)

    print(f"\n  Processed: {len(all_metadata)}, Skipped: {skipped}")

    # Save all extracted metadata
    with open(os.path.join(OUTPUT_DIR, "sessions_metadata.json"), "w") as f:
        json.dump(all_metadata, f, indent=2, ensure_ascii=False)

    # Step 3: Create aggregated files
    print("\n[3/4] Creating aggregated files...")
    user_profile, apps_catalog, decisions_log, corrections_log = create_aggregated_files(all_metadata)

    # Step 4: Create README
    print("\n[4/4] Creating README...")
    create_readme(
        total_sessions=len(all_sessions),
        processed=len(all_metadata),
        apps_count=len(apps_catalog),
        decisions_count=len(decisions_log),
        corrections_count=len(corrections_log)
    )

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print(f"  Sessions: {len(all_sessions)} total, {len(all_metadata)} processed")
    print(f"  Apps found: {len(apps_catalog)}")
    print(f"  Decisions: {len(decisions_log)}")
    print(f"  Corrections: {len(corrections_log)}")
    print(f"  Output: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
