from __future__ import annotations

import json

from kanka_scribe.registry import allowed_modules

# Shared structure for session journals (Notion Session Overview template).
SESSION_RECAP_STRUCTURE = """
### Session Overview
**Session Number:** …
**Date Played:** … (prefer YYYY-MM-DD or a clear calendar date from the transcript/title)
**In-Game Date/Season:** … (or Unknown)
**Party Level:** … (or Unknown)
**Party Members Present:**
- Name (brief class/role if known) — use exact cast Player Character names

### Narrative Recap
Write a flowing 2–4 paragraph story of the session as if recounting it to someone who missed the game. Focus on what the party did, where they went, and how events unfolded. Highlight tension, surprises, and character-driven moments. Keep it immersive rather than mechanical.

### Story Beats & Turning Points
Describe the major moments of the session in short narrative form. Each entry should feel like a beat in the story rather than a bullet of facts.
- **Opening Situation:** Where the party started and their immediate goal.
- **Rising Action:** Key developments, discoveries, or complications.
- **Climax:** The most intense or decisive moment (combat, confrontation, revelation).
- **Resolution:** How the situation settled and what changed as a result.

### Kingdom & World State
Describe how the kingdom and surrounding world evolved this session. Focus on narrative impact rather than raw stats. Omit the whole section if nothing kingdom-scale happened.
- **Changes to the Kingdom:** Growth, instability, political developments, or notable decisions.
- **Events or Crises:** What happened and how it was handled.
- **Expansion & Exploration:** New lands, settlements, or discoveries and what they mean for the future.

### Character Moments
Capture individual spotlight moments with a storytelling focus.
- **Character Name:** Describe their standout scene, decision, or growth moment.

### Relationships & NPCs
Summarize meaningful interactions and evolving dynamics.
- **NPC Name:** Who they are, what happened this session, and how their relationship with the party changed.

### Conflicts & Encounters
Describe major conflicts in narrative form rather than mechanical detail.
- **Encounter Description:** What made this conflict interesting (terrain, stakes, tactics, emotions).
- **Outcome:** Who prevailed and at what cost.
- **Notable Twist or Moment:** Anything unexpected or cinematic.

### Discoveries, Clues & Lore
Present important information as story revelations.
- **What was learned:** Describe the clue or lore naturally.
- **Why it matters:** Connect it to larger mysteries or goals.

### Quests & Ongoing Threads
Frame these as narrative threads rather than checklists.
- **Active Thread:** What the party is currently pursuing and why it matters.
- **Completed Thread:** How it concluded and its impact on the world.
- **New Hook:** A newly introduced opportunity, threat, or mystery.

### Tone & Table Highlights
Capture the emotional and social energy of the session.
- **Most Epic Moment:** …
- **Most Chaotic Moment:** …
- **Funniest Moment:** …
- **Most Unexpected Outcome:** …

### Memorable Quotes
Include quotes that reflect character, humor, or dramatic tension.
- "Quote" — Character/Player context

### Consequences & Forward Momentum
- **Immediate Consequences:** What has already changed.
- **Brewing Tensions:** Problems or risks that are escalating.
- **Opportunities:** New paths, alliances, or advantages opened up.

### Looking Ahead
- **Where the party is now:** Physical and narrative position.
- **What they intend to do next:** Stated plans or implied direction.
- **GM Foreshadowing (optional):** Any hints or looming elements.

### AI Notes (Optional)
Light meta-observations that support future summaries.
- **Narrative Themes Emerging:** …
- **Player Engagement Signals:** …
- **Threads Worth Emphasizing Next Session:** …
""".strip()

SYSTEM = f"""You are Goblin Scribe, the campaign chronicler for a tabletop RPG group.
Write a campaign-wiki session journal in markdown using this exact section structure and headings:

{SESSION_RECAP_STRUCTURE}

Hard rules:
- Use the ### headings above exactly (including Session Overview).
- Prefer exact Player Character cast names; map speakers/nicknames to the cast list.
- Past tense. Immersive and narrative — not a mechanical combat log.
- Do not invent events missing from the transcript. Unknown fields may be "Unknown" or omitted.
- Do not dump raw dialogue except short decisive quotes in Memorable Quotes.
- Omit a whole ### section only when the transcript truly has nothing for it (never omit Session Overview, Narrative Recap, Story Beats, Quests & Ongoing Threads, Looking Ahead).
- No markdown fences. No preamble outside the journal."""

CHUNK_SYSTEM = """You are Goblin Scribe summarizing ONE CHUNK of a longer session transcript into notes for a Session Overview journal.
Capture, for this chunk only (past tense, grounded — do not invent later-session events):
- Party actions, places, named PCs (use cast names), NPCs, organisations
- Story beats (setup / complications / climax-like moments / outcomes in this chunk)
- Character spotlight moments, relationship shifts
- Conflicts/encounters (narrative stakes, not dice math)
- Discoveries, clues, lore; quest threads advanced or introduced
- Memorable quotes; tone/table energy if clear
Use short ### subheads or bold labels as needed. Narrative paragraphs preferred over thin bullets.
Do not write a final merged journal yet. No preamble about chunking."""

MERGE_SYSTEM = f"""You are Goblin Scribe merging partial session notes into ONE final campaign journal.
Produce a single coherent markdown document using this exact structure and headings:

{SESSION_RECAP_STRUCTURE}

Hard rules:
- Deduplicate. Preserve chronology. Attribute actions to cast characters when named.
- Full wiki length — not a stub. Narrative Recap must be 2–4 real paragraphs.
- Past tense, immersive, grounded in the partials. No meta commentary about chunks.
- No markdown fences. No preamble outside the journal."""

STORY_TITLE_SYSTEM = """You name tabletop RPG sessions.
Given a session recap, reply with ONLY a short story title (3 to 8 words).
No quotes, no markdown, no prefix like "Title:", no date, no "Session"."""

CLEAN_TRANSCRIPT_SYSTEM = """You clean tabletop RPG session transcripts for the campaign archive.

Rewrite the input chunk as a cleaned transcript:
- REMOVE off-topic / out-of-character chatter (pets, apps, tech issues, scheduling, rules digressions that do not affect the fiction, side banter unrelated to play).
- KEEP in-character dialogue, GM narration, rulings that change the fiction, combat, exploration, and clear scene setup.
- KEEP speaker labels exactly as given (they may already be character names). Do NOT invent speakers when none are labeled.
- When the chunk has NO speaker labels (continuous paragraphs / meeting-notes paste), keep nearly all play-relevant narration and dialogue as continuous paragraphs. Only drop clearly off-topic asides. Do not collapse the session into a short summary.
- KEEP timestamps exactly as written when present ([00:12:34], 1:23:45, etc.). Never invent timestamps.
- Preserve chronological order. Light grammar cleanup is OK; do not invent plot.
- Output ONLY the cleaned transcript text for this chunk (no preamble, no markdown fences, no commentary)."""

CLEAN_MERGE_SYSTEM = """You merge cleaned transcript chunks into one continuous cleaned transcript.
Preserve speaker labels and timestamps. Remove duplicate seams. Do not reintroduce off-topic talk. Output ONLY the merged transcript."""

SESSION_META_SYSTEM = """Extract session metadata from a tabletop RPG transcript and/or recap.
Return ONLY valid JSON (no markdown fences) of the form:
{"session":"1","date":"2025-12-14","time":"19:00","participants":["Lyra"],"locations":["Heatherland"]}

Rules:
- session: session number or label if stated; otherwise "Unknown"
- date: the date the session was PLAYED (look for Date Played, session date, title dates). Prefer ISO YYYY-MM-DD. This is often a past date when backfilling old transcripts — never substitute today's date or the ingest date.
- time: start time or time of day if stated; otherwise "Unknown"
- participants: player-character names clearly present (prefer cast list names)
- locations: place names clearly present
- Never invent. Use "Unknown" or [] when unsure.
- No commentary outside JSON."""


def format_cast_block(characters: list[dict]) -> str:
    """Format cast for LLM prompts: Player Characters first, then others.

    PC vs other is determined solely by each row's character_type from Kanka
    (Type field), not by hard-coded names.
    """
    from kanka_scribe.kanka_entities import is_player_character_type

    if not characters:
        return ""

    def _line(ch: dict) -> str:
        name = str(ch.get("name") or "").strip()
        aliases = [str(a).strip() for a in (ch.get("aliases") or []) if str(a).strip()]
        if aliases:
            return f"- {name} (also: {', '.join(aliases)})"
        return f"- {name}"

    pcs: list[dict] = []
    others: list[dict] = []
    for ch in characters:
        if not str(ch.get("name") or "").strip():
            continue
        if is_player_character_type(ch.get("character_type")):
            pcs.append(ch)
        else:
            others.append(ch)

    lines: list[str] = []
    if pcs:
        lines.append(
            "Player Characters (match speakers/participants to these exact names first):"
        )
        lines.extend(_line(ch) for ch in pcs)
    if others:
        if lines:
            lines.append("")
        lines.append(
            "Other known characters (NPCs — do not merge into Player Characters):"
        )
        lines.extend(_line(ch) for ch in others)
    if not lines:
        return ""
    return "\n".join(lines)


def _with_context(
    system: str,
    *,
    campaign_context: str = "",
    cast_block: str = "",
) -> str:
    parts = [system]
    if cast_block.strip():
        parts.append(cast_block.strip())
    if campaign_context.strip():
        parts.append("Campaign context (continuity only):\n" + campaign_context.strip())
    return "\n\n".join(parts)


def resolve_recap_system(system_prompt: str | None = None) -> str:
    """Return workspace override or the built-in Session Overview system prompt."""
    custom = (system_prompt or "").strip()
    return custom if custom else SYSTEM


def normalize_recap_system_prompt(system_prompt: str | None) -> str:
    """Persist empty when matching the built-in default so upgrades apply."""
    custom = (system_prompt or "").strip()
    if not custom or custom == SYSTEM.strip():
        return ""
    return custom


def _merge_system(system_prompt: str | None = None) -> str:
    custom = (system_prompt or "").strip()
    if not custom:
        return MERGE_SYSTEM
    return (
        "You are Goblin Scribe merging partial session notes into ONE final "
        "campaign journal.\n"
        "Produce a single coherent markdown document following these "
        "instructions:\n\n"
        f"{custom}\n\n"
        "Additional merge rules:\n"
        "- Deduplicate. Preserve chronology. Attribute actions to cast "
        "characters when named.\n"
        "- Full wiki length — not a stub.\n"
        "- Past tense, immersive, grounded in the partials. No meta "
        "commentary about chunks.\n"
        "- No markdown fences. No preamble outside the journal."
    )


def build_messages(
    transcript: str,
    campaign_context: str = "",
    cast_block: str = "",
    system_prompt: str | None = None,
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": _with_context(
                resolve_recap_system(system_prompt),
                campaign_context=campaign_context,
                cast_block=cast_block,
            ),
        },
        {"role": "user", "content": transcript},
    ]


def build_chunk_messages(
    chunk: str,
    index: int,
    total: int,
    campaign_context: str = "",
    cast_block: str = "",
) -> list[dict]:
    header = f"Transcript chunk {index}/{total}:\n\n"
    return [
        {
            "role": "system",
            "content": _with_context(
                CHUNK_SYSTEM, campaign_context=campaign_context, cast_block=cast_block
            ),
        },
        {"role": "user", "content": header + chunk},
    ]


def build_merge_messages(
    partial_recaps: list[str],
    campaign_context: str = "",
    cast_block: str = "",
    system_prompt: str | None = None,
) -> list[dict]:
    body = "\n\n---\n\n".join(
        f"### Partial recap {i}/{len(partial_recaps)}\n\n{text.strip()}"
        for i, text in enumerate(partial_recaps, start=1)
        if text.strip()
    )
    return [
        {
            "role": "system",
            "content": _with_context(
                _merge_system(system_prompt),
                campaign_context=campaign_context,
                cast_block=cast_block,
            ),
        },
        {"role": "user", "content": body},
    ]


def build_story_title_messages(recap: str) -> list[dict]:
    return [
        {"role": "system", "content": STORY_TITLE_SYSTEM},
        {"role": "user", "content": recap},
    ]


def build_clean_chunk_messages(
    chunk: str,
    index: int,
    total: int,
    cast_block: str = "",
) -> list[dict]:
    system = CLEAN_TRANSCRIPT_SYSTEM
    if cast_block.strip():
        system += (
            "\n\nCast (for context only; do not rename speakers unless already labeled):\n"
            + cast_block.strip()
        )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Transcript chunk {index}/{total}:\n\n{chunk}",
        },
    ]


def build_clean_merge_messages(partials: list[str]) -> list[dict]:
    body = "\n\n---\n\n".join(
        f"### Cleaned chunk {i}/{len(partials)}\n\n{text.strip()}"
        for i, text in enumerate(partials, start=1)
        if text.strip()
    )
    return [
        {"role": "system", "content": CLEAN_MERGE_SYSTEM},
        {"role": "user", "content": body},
    ]


def build_session_meta_messages(
    *,
    transcript: str,
    recap: str = "",
    cast_block: str = "",
) -> list[dict]:
    parts = [SESSION_META_SYSTEM]
    if cast_block.strip():
        parts.append(cast_block.strip())
    user_bits = []
    if recap.strip():
        user_bits.append("Recap:\n" + recap.strip()[:6000])
    # Keep transcript snippet bounded for a cheap metadata pass
    if transcript.strip():
        user_bits.append("Transcript excerpt:\n" + transcript.strip()[:8000])
    return [
        {"role": "system", "content": "\n\n".join(parts)},
        {"role": "user", "content": "\n\n".join(user_bits) or "(empty)"},
    ]


DETAIL_SYSTEM_HEADER = """You enrich known campaign entities using a transcript chunk and fill Kanka metadata fields.
Return ONLY valid JSON:
{"details":[{"name":"Lyra","type":"character","summary":"...","evidence":["..."],"aliases":[],"fields":{}}],"memberships":[{"character":"Lyra","organisation":"Roving Guard","role":"scout"}],"events":[{"name":"Battle at the Dam","summary":"...","evidence":["..."],"fields":{}}]}

Global rules:
- Only detail entities from the known-entity list (same name or clear alias). Do not invent new entity names in details.
- memberships: ALWAYS list character↔organisation links when affiliation is stated or strongly implied (military units, guilds, churches, tribes). Include role/rank when known (e.g. role "Lieutenant"). Prefer the organisation's proper name ("the Sentinels", "Sentinels").
- events: distinct named happenings in this chunk. Prefer proper names ("Battle at the Dam").
- EVERY summary (details and events) MUST be verbose campaign-wiki prose (~100–350 words, 2–5 short paragraphs, past tense), grounded only in this chunk. Do not invent.
- evidence: 2–5 short quotes or paraphrases. Empty lists OK. No markdown fences.
- Always include a "fields" object. Omit a field or use null when unknown — never invent ages, genders, locations, or dates.
- Each module has its OWN Type vocabulary (below). Never put a character Type value on an organisation/quest/etc., and never put freeform job titles in character Type.

Per-type fields (put inside fields; use plain names, not Kanka ids):"""

ENTITY_TYPE_PROMPT_KEYS = (
    "character",
    "location",
    "organisation",
    "creature",
    "quest",
    "item",
    "event",
    "other",
)

ENTITY_TYPE_HEADINGS = {
    "character": "### character",
    "location": "### location",
    "organisation": "### organisation",
    "creature": "### creature",
    "quest": "### quest",
    "item": "### item",
    "event": "### event",
    "other": "### other types (race, family, note, …)",
}

ENTITY_TYPE_LABELS = {
    "character": "Character",
    "location": "Location",
    "organisation": "Organisation",
    "creature": "Creature",
    "quest": "Quest",
    "item": "Item",
    "event": "Event",
    "other": "Other (race, family, note, …)",
}

DEFAULT_ENTITY_TYPE_PROMPTS = {
    "character": """- type: MUST be exactly one of: "NPC", "Player Character", "Deity" (PCs from the cast → Player Character; gods → Deity; everyone else → NPC). Never "officer", "sentinel", "villager", etc.
- title: job/rank/office (e.g. "Lieutenant", "Mayor", "Archery Trainer") — put roles here, not in type
- organisations: array of {name, role} affiliations for this character (also emit matching memberships entries)
- age, sex (gender), pronouns when stated
- locations: place names where they live, work, or were encountered
- races: race/species names if stated
- appearance: array of {name, entry} traits
- personality: array of {name, entry} traits""",
    "location": """- type: place kind — prefer City, Kingdom, Ruin, Village, Town, District, Building, Landmark, Forest, Mountain, Keep, Temple, Tavern, Wilderness, Dungeon, Region (or a similar short label)
- parent: containing region/settlement name if clear""",
    "organisation": """- type: group kind — prefer Cult, Gang, Rebellion, Fandom, Military, Guild, Religion, Government, Tribe, Order, Church, Company, Cabal (or a similar short label)
- locations: HQ or associated place names""",
    "creature": """- type: creature kind — prefer Herbivore, Aquatic, Mythical, Carnivore, Omnivore, Beast, Humanoid, Undead, Dragon, Swarm (or a similar short label)
- locations: where encountered""",
    "quest": """- type: MUST be exactly one of: "Character Arc", "Sidequest", "Main"
- instigator: character/NPC name who gave or drives the quest
- locations: places the quest concerns
- date: played-on or started date if stated (prefer YYYY-MM-DD)""",
    "item": """- type: MUST be exactly one of: "Weapon", "Potion", "Artifact" (maps, documents, relics, gear → Artifact unless clearly a weapon or potion)
- location: where it is / was found
- price, size, weight: only if stated
- creators: maker names if stated""",
    "event": """- type: Battle, Ambush, Discovery, Ceremony, Death, Journey, Negotiation, Disaster, Other (or closest fit)
- date: when it happened if stated (prefer YYYY-MM-DD)
- locations: where it happened""",
    "other": """- type: short module-appropriate label when useful
- locations: related place names when applicable""",
}


def parse_entity_type_prompts(raw: str | dict | None) -> dict[str, str]:
    """Parse stored overrides; ignore unknown keys and empty values."""
    if isinstance(raw, dict):
        data = raw
    else:
        text = (raw or "").strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
    out: dict[str, str] = {}
    for key in ENTITY_TYPE_PROMPT_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def resolve_entity_type_prompts(raw: str | dict | None = None) -> dict[str, str]:
    """Effective per-type prompts (defaults merged with workspace overrides)."""
    overrides = parse_entity_type_prompts(raw)
    return {
        key: overrides.get(key) or DEFAULT_ENTITY_TYPE_PROMPTS[key]
        for key in ENTITY_TYPE_PROMPT_KEYS
    }


def normalize_entity_type_prompts(prompts: dict[str, str] | None) -> str:
    """Persist JSON of only non-default overrides (empty string = all defaults)."""
    overrides: dict[str, str] = {}
    for key in ENTITY_TYPE_PROMPT_KEYS:
        value = (prompts or {}).get(key, "")
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped:
            continue
        if stripped == DEFAULT_ENTITY_TYPE_PROMPTS[key].strip():
            continue
        overrides[key] = stripped
    if not overrides:
        return ""
    return json.dumps(overrides, ensure_ascii=False, indent=2)


def assemble_detail_system(entity_type_prompts: str | dict | None = None) -> str:
    effective = resolve_entity_type_prompts(entity_type_prompts)
    sections = [
        f"{ENTITY_TYPE_HEADINGS[key]}\n{effective[key]}"
        for key in ENTITY_TYPE_PROMPT_KEYS
    ]
    return DETAIL_SYSTEM_HEADER + "\n\n" + "\n\n".join(sections)


# Built-in assembled prompt (tests / callers that expect a single constant).
DETAIL_SYSTEM = assemble_detail_system()


def build_detail_messages(
    chunk: str,
    *,
    known_entities: list[dict],
    cast_block: str = "",
    entity_type_prompts: str | dict | None = None,
) -> list[dict]:
    lines = ["Known entities (detail only these):"]
    for ent in known_entities:
        name = str(ent.get("name") or "").strip()
        typ = str(ent.get("type") or ent.get("module") or "").strip()
        if name:
            lines.append(f"- {typ}: {name}" if typ else f"- {name}")
    system = assemble_detail_system(entity_type_prompts) + "\n\n" + "\n".join(lines)
    if cast_block.strip():
        system += "\n\n" + cast_block.strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": chunk},
    ]


def build_extract_messages(
    chunk: str,
    profile: str = "ce",
    cast_block: str = "",
) -> list[dict]:
    types = ", ".join(allowed_modules(profile))
    system = f"""You extract worldbuilding entities from a tabletop RPG session recap or transcript chunk.
Return ONLY valid JSON of the form:
{{"entities":[{{"type":"character","name":"Lyra","aliases":["the rogue"],"summary":"...","confidence":"high","evidence":["..."]}}]}}

Rules:
- type must be one of: {types}
- Prefer: character, location, quest, item, creature, organisation, event, note, race, family.
- Extract EVERY distinct named place, NPC, PC, quest/objective, item/loot, faction, creature, and notable event.
- Use proper names (Heatherland Village, Lieutenant Donovan) — not generic nouns alone (compound, tree line) unless that is the only name given.
- Map player characters to the cast list exact names (confidence high).
- NPCs are type "character". Quests/objectives are type "quest". Loot and named objects are type "item". Events need proper names ("Battle at the Dam").
- summary for EVERY entity MUST be verbose campaign-wiki prose (~100–350 words, 2–5 short paragraphs, past tense), never 1–3 thin sentences. Stay faithful to the chunk; do not invent. Emphasize by type:
  - character: look/demeanor if given, role, actions, motives shown, ties to party/factions.
  - location: place in the world, layout/atmosphere from play, what happened there, why it matters.
  - organisation: purpose, methods, named members/leaders, party's dealings, current standing.
  - creature: look/behavior, tactics/abilities shown, encounter site, how it went, result.
  - quest: goal, stakes, progress, blockers, open questions.
  - item: nature, provenance this session, properties/clues, holder, significance.
  - event: setup, participants, action/turning points, outcome, fallout.
- evidence: 2–5 short supporting quotes or paraphrases when available.
- Do not create journal/note entities for the play session itself.
- confidence is high, medium, or low. Named proper nouns from the recap header or clear narration → high/medium.
- Be thorough; missing entities is worse than a few low-confidence extras.
- No markdown fences. No commentary outside JSON."""
    if cast_block.strip():
        system += "\n\n" + cast_block.strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": chunk},
    ]
