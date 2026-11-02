"""What may cross from the local zone to the frontier model.

An ALLOWLIST: a field crosses only if it is named here for that item type and privacy level.
Anything else (raw titles, descriptions, locations, clarifying questions, rule details) stays local
by default, including fields added to records later that nobody thought about.
"""

LEVELS = {
    0: "structure",  # ids, types, goals, dates — no words at all
    1: "actions",    # + pseudonymized people/orgs and next actions for actionable items
    2: "content",    # + pseudonymized note text for actionable notes
}
DEFAULT_LEVEL = 1

# Never send any text for these, at any level: reflections and friends' goals are the most private data.
NEVER_TEXT = {"musing", "good_words", "other_person_goal"}
# Items the frontier agent can plan around.
ACTIONABLE = {"event", "action", "project_idea", "business_idea", "learning_topic", "goal"}
# Note types whose (pseudonymized) text may cross at level 2. Events are excluded: their titles
# carry places and context that a planner doesn't need.
TEXT_AT_LEVEL_2 = ACTIONABLE - {"event"}

BASE_KEYS = {"handle", "type", "date", "goal_links", "confidence", "pending_clarification"}
EVENT_KEYS = {"start", "end"}
MUSING_KEYS = {"musing_theme"}
ACTION_SUMMARY_KEYS = {"has_next_action", "people_count"}
LEVEL_1_KEYS = {"people", "org", "next_action"}
LEVEL_2_KEYS = {"text"}

ALLOWED_KEYS = BASE_KEYS | EVENT_KEYS | MUSING_KEYS | ACTION_SUMMARY_KEYS | LEVEL_1_KEYS | LEVEL_2_KEYS
TEXT_KEYS = {"next_action", "text"}  # free-text fields: checked hardest

# Words that name a group, not a person. A labeler (human or model) sometimes puts these in `people`;
# pseudonymizing them would erase ordinary words everywhere, so they are ignored.
GROUP_WORDS = {"friends", "family", "team", "everyone", "people", "us", "them", "guys", "folks", "parents"}
