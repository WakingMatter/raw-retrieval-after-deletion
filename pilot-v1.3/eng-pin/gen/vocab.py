"""Static vocabulary: names, value pools, slot labels and prose templates.

Slot *labels* (``office_city`` ...) are internal identifiers. They are
snake_case on purpose so that a verbatim label in rendered prose is detectable
(generator test: no key or slot label in prose unless scripted). Prose uses the
natural-language templates below, never the label.
"""
from __future__ import annotations

PERSON_FIRST = ["Priya", "Arjun", "Meera", "Kabir", "Ananya", "Rohan", "Ishaan", "Diya", "Vikram",
                "Nisha", "Tara", "Dev", "Leela", "Sameer", "Zoya", "Farhan", "Kavya", "Neel",
                "Aisha", "Rahul", "Maya", "Omar", "Ines", "Lucas", "Hana", "Felix", "Sofia",
                "Mateo", "Elena", "Yusuf"]
# last name -> look-alike last name
PERSON_LAST_TWIN = {"Raman": "Ramani", "Iyer": "Iyengar", "Kapoor": "Kapur", "Menon": "Mennon",
                    "Shah": "Shahi", "Bose": "Basu", "Nair": "Naik", "Mehta": "Mehra",
                    "Sethi": "Sethia", "Pillai": "Pillay", "Varma": "Verma", "Joshi": "Joshua",
                    "Khanna": "Khana", "Ghosh": "Ghose", "Reddy": "Reddi", "Chopra": "Chopda"}
PROJECTS = ["Atlas", "Halcyon", "Juniper", "Meridian", "Nimbus", "Orchid", "Quasar", "Saffron",
            "Tundra", "Vesper", "Cobalt", "Ember", "Falcon", "Lumen", "Mosaic", "Pylon", "Sable",
            "Zephyr"]
PROJECT_TWIN_SUFFIX = " Lite"
SERVICES = ["ledger-api", "search-indexer", "auth-gateway", "notif-hub", "media-proxy",
            "metrics-sink", "order-router", "profile-store", "quota-guard", "ranker-svc",
            "session-cache", "sync-daemon", "tile-server", "vault-bridge"]
SERVICE_TWIN_SUFFIX = "-v2"
CONFIGS = ["rate-limit policy", "retry policy", "checkout timeout policy", "ingest throttle",
           "webhook policy", "export policy", "cache policy", "upload policy"]
CONFIG_TWIN_PREFIX = "legacy "

POOLS = {
    "office_city": ["Pune", "Bengaluru", "Hyderabad", "Chennai", "Delhi", "Mumbai", "Kolkata",
                    "Jaipur", "Kochi", "Indore", "Lisbon", "Berlin", "Austin", "Toronto",
                    "Singapore", "Dublin"],
    "team_name": ["Payments", "Search Quality", "Core Infra", "Growth", "Data Platform", "Mobile Apps",
                  "AppSec", "Billing Ops", "Identity", "Observability", "Storefront", "Ads Ranking"],
    "job_role": ["staff engineer", "engineering manager", "product manager", "SRE lead",
                 "data scientist", "product designer", "tech lead", "QA lead", "solutions architect"],
    "proj_status": ["in planning", "in design review", "in active build", "paused", "in beta",
                    "shipped", "in maintenance mode"],
    "proj_deadline": ["March 14", "April 3", "April 28", "May 19", "June 9", "June 30", "July 21",
                      "August 11", "September 1", "September 22", "October 13", "November 3"],
    "repo_name": ["{p}-core", "{p}-mono", "{p}-next", "{p}-platform", "{p}-app", "{p}-svc",
                  "{p}-stack", "{p}-hub"],
    "host_region": ["us-east-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-south-1",
                    "ap-southeast-1", "sa-east-1", "ca-central-1", "ap-northeast-1"],
    "listen_port": ["8080", "8443", "9000", "9090", "7000", "5000", "6060", "3000", "8000", "8888",
                    "7443", "9443"],
    "db_engine": ["Postgres", "MySQL", "Cassandra", "DynamoDB", "CockroachDB", "MongoDB",
                  "ScyllaDB", "Spanner"],
    "cfg_max_rps": ["200", "250", "400", "500", "750", "1000", "1500", "2000", "3000"],
    "cfg_timeout_ms": ["250", "500", "800", "1200", "1500", "2500", "3000", "5000"],
}

# entity type -> slots. ref slots take a person's display name as value.
TYPE_SLOTS = {
    "person": ["office_city", "team_name", "job_role"],
    "project": ["proj_lead", "proj_status", "proj_deadline", "repo_name"],
    "service": ["svc_owner", "host_region", "listen_port", "db_engine"],
    "config": ["cfg_max_rps", "cfg_timeout_ms"],
}
MANDATORY_SLOTS = {"office_city", "team_name", "proj_lead", "svc_owner"}
REF_SLOTS = {"proj_lead", "svc_owner"}
# derived slot -> (entity type, ref slot, person attr slot)
DERIVED_SLOTS = {
    "lead_office_city": ("project", "proj_lead", "office_city"),
    "lead_team_name": ("project", "proj_lead", "team_name"),
    "owner_office_city": ("service", "svc_owner", "office_city"),
    "owner_team_name": ("service", "svc_owner", "team_name"),
}
ALL_SLOT_LABELS = sorted(set(sum(TYPE_SLOTS.values(), [])) | set(DERIVED_SLOTS))

# Short noun used by probe/warm-up/operator templates.
SLOT_NOUN = {
    "office_city": "office city", "team_name": "team", "job_role": "role",
    "proj_lead": "project lead", "proj_status": "status", "proj_deadline": "deadline",
    "repo_name": "repository", "svc_owner": "owner", "host_region": "hosting region",
    "listen_port": "port", "db_engine": "database", "cfg_max_rps": "request ceiling (rps)",
    "cfg_timeout_ms": "timeout (ms)",
    "lead_office_city": "project lead's office city", "lead_team_name": "project lead's team",
    "owner_office_city": "owner's office city", "owner_team_name": "owner's team",
}

# ------------------------------------------------------------------ prose templates
# {s} subject display name, {v} value, {s2}/{v2} the bait twin, {d} reverted change date.
T = {}
T["office_city"] = {
    "assert": ["{s} works out of the {v} office.", "{s} is based in our {v} office.",
               "{s}'s desk is in the {v} office."],
    "se": ["Update: {s} has moved to the {v} office.", "Heads-up: {s} relocated to {v} this week, so the old desk is free."],
    "si": ["{s} was at their desk in the {v} office all week and ran the team sync from there.",
           "Badge logs show {s} at their desk in {v} every day."],
    "restate": ["As usual, {s} is working from the {v} office."],
    "reread": ["From an older page of notes: {s} sits in the {v} office.", "{s} sits in the {v} office."],
    "tset": ["Correction: {s} is actually in the {v} office."],
    "tvoid": ["Ignore my correction about {s}'s office, I mixed two people up; {s} is still in {v}."],
    "return": ["Reverting the earlier move: {s} is back in the {v} office (rolling back the change from {d})."],
    "retract": ["Scratch what I said about where {s} is based; it was never confirmed, so treat it as unknown for now."],
    "bait": "{s} works out of the {v} office, while {s2} works out of the {v2} office.",
    "hypo": "If {s} ever moved to the {v} office we would have to redo the whole seating plan, but nobody is proposing that; it was a what-if in the planning chat.",
    "neardup": "Facilities says {s}'s parking pass is still registered at the {v} campus garage, which is a paperwork leftover and has nothing to do with where anyone sits.",
    "quoted": "> Archived wiki page (pre-reorg, do not trust): \"{s} - {v} office.\" That page has not been maintained for years.",
    "stale": "Old TODO from a planning doc that was never actioned: ask whether {s} might want to try the {v} office for a quarter.",
}
T["team_name"] = {
    "assert": ["{s} is on the {v} team.", "{s} works with the {v} team."],
    "se": ["Update: {s} has transferred to the {v} team.", "Org change: {s} now reports into {v}."],
    "si": ["{s} presented the {v} team's sprint review and owns two of its tickets.",
           "{s} is listed on the {v} team's on-call rotation and attends its standups."],
    "restate": ["{s} is still with the {v} team."],
    "reread": ["From an old org chart printout: {s} is on the {v} team.", "{s} is on the {v} team."],
    "tset": ["Correction: {s} is actually on the {v} team."],
    "tvoid": ["Disregard my correction about {s}'s team, wrong person; {s} remains on the {v} team."],
    "return": ["Reverting the team change: {s} is back on the {v} team (rolling back the move from {d})."],
    "retract": ["I need to retract what I said about which team {s} is on; nobody can confirm it, so leave it unknown."],
    "bait": "{s} is on the {v} team, while {s2} is on the {v2} team.",
    "hypo": "In the reorg brainstorm someone floated putting {s} on the {v} team; it was only a brainstorm and was not adopted.",
    "neardup": "{s} sat in on a {v} team brown-bag last month as a guest, purely out of curiosity.",
    "quoted": "> From a 2028 slide deck: \"{s} ({v})\". The deck predates two reorganisations.",
    "stale": "Stale reminder in the tracker: check if {s} wants a rotation with the {v} team someday.",
}
T["job_role"] = {
    "assert": ["{s} is a {v}.", "{s}'s role is {v}."],
    "se": ["Update: {s} has been promoted, and is now a {v}.", "Role change: {s} moved into a {v} position."],
    "si": ["{s} ran the hiring loop as the {v} on the panel and signed the offer packet in that capacity."],
    "restate": ["{s} is still our {v}."],
    "reread": ["From the old directory export: {s}, {v}.", "{s} is a {v}."],
    "tset": ["Correction: {s} is actually a {v}."],
    "tvoid": ["Ignore my correction about {s}'s role; that was someone else. {s} is still a {v}."],
    "return": ["Reverting the role change: {s} is a {v} again (rolling back the change from {d})."],
    "retract": ["Retracting my note about {s}'s role; HR has not confirmed anything, so treat it as unknown."],
    "bait": "{s} is a {v}, while {s2} is a {v2}.",
    "hypo": "Hypothetically, if {s} became a {v}, the team would need a new interviewer; nothing is planned.",
    "neardup": "{s} filled in as acting {v} for one afternoon while someone was out, which was a one-off.",
    "quoted": "> Old badge record (expired): \"{s} - {v}\". The record was never updated.",
    "stale": "Stale career-plan note: discuss whether {s} could grow into a {v} role eventually.",
}
T["proj_lead"] = {
    "assert": ["{s} is led by {v}.", "{v} leads {s}."],
    "se": ["Update: {v} has taken over as lead of {s}.", "Leadership change: {s} is now led by {v}."],
    "si": ["{v} chaired the {s} kickoff and signs off on every {s} design decision."],
    "restate": ["{v} is still leading {s}."],
    "reread": ["From the old project charter: {s} lead is {v}.", "{v} leads {s}."],
    "tset": ["Correction: {s} is actually led by {v}."],
    "tvoid": ["Ignore my correction about who leads {s}; it was a mix-up. {v} still leads it."],
    "return": ["Reverting the leadership change: {v} is leading {s} again (rolling back the handover from {d})."],
    "retract": ["Retracting what I said about who leads {s}; it is not settled, so treat the lead as unknown."],
    "bait": "{s} is led by {v}, while {s2} is led by {v2}.",
    "hypo": "If {v} were ever asked to lead {s}, they would need to drop other work; this was a hypothetical in a staffing chat.",
    "neardup": "{v} reviewed a single {s} pull request last sprint as a favour, nothing more.",
    "quoted": "> Draft charter that was never approved: \"{s} - lead: {v}\".",
    "stale": "Old TODO: ask {v} whether they would ever be interested in {s}.",
}
T["proj_status"] = {
    "assert": ["{s} is {v}.", "Status check: {s} is {v}."],
    "se": ["Update: {s} has changed status and is now {v}.", "Status change for {s}: it is now {v}."],
    "si": ["The {s} weekly report is filed under the {v} column and the team planned this week accordingly."],
    "restate": ["{s} remains {v}."],
    "reread": ["From an old status email: {s} is {v}.", "{s} is {v}."],
    "tset": ["Correction: {s} is actually {v}."],
    "tvoid": ["Ignore my correction about {s}'s status; I read the wrong row. {s} is still {v}."],
    "return": ["Reverting the status change: {s} is {v} again (rolling back the change from {d})."],
    "retract": ["Retracting my note on {s}'s status; nobody can confirm it, so treat the status as unknown."],
    "bait": "{s} is {v}, while {s2} is {v2}.",
    "hypo": "If {s} were {v}, the roadmap slide would look very different; that is not the case, it was a scenario exercise.",
    "neardup": "A sister initiative that shares {s}'s chat channel is {v}, which keeps confusing new joiners.",
    "quoted": "> Ancient roadmap export: \"{s}: {v}\". The export is from before the project was rescoped.",
    "stale": "Stale question in the backlog: could {s} ever be {v}?",
}
T["proj_deadline"] = {
    "assert": ["{s} is due on {v}.", "The deadline for {s} is {v}."],
    "se": ["Update: the {s} deadline has moved to {v}.", "Schedule change: {s} is now due {v}."],
    "si": ["The {s} launch checklist is counting down to {v} and marketing has booked that date."],
    "restate": ["{s} is still due {v}."],
    "reread": ["From an earlier planning sheet: {s} due {v}.", "{s} is due on {v}."],
    "tset": ["Correction: {s} is actually due on {v}."],
    "tvoid": ["Ignore my correction about the {s} deadline; wrong project. It is still {v}."],
    "return": ["Reverting the schedule change: {s} is due {v} again (rolling back the slip from {d})."],
    "retract": ["Retracting the {s} deadline I shared; it was not agreed, so treat the date as unknown."],
    "bait": "{s} is due on {v}, while {s2} is due on {v2}.",
    "hypo": "If {s} had to land by {v} we would need extra people; nobody has asked for that, it was a what-if.",
    "neardup": "The {s} design review, not the launch, was pencilled in for {v}.",
    "quoted": "> Superseded draft schedule: \"{s} - {v}\". Never adopted.",
    "stale": "Old TODO: check whether {v} could ever work for {s}.",
}
T["repo_name"] = {
    "assert": ["{s} code lives in the {v} repository.", "The {s} repo is {v}."],
    "se": ["Update: {s} code has moved to the {v} repository.", "Repo migration done: {s} now lives in {v}."],
    "si": ["All new {s} pull requests are being opened against {v} and CI runs from there."],
    "restate": ["{s} code is still in {v}."],
    "reread": ["From an old README: {s} lives in {v}.", "The {s} repo is {v}."],
    "tset": ["Correction: the {s} repo is actually {v}."],
    "tvoid": ["Ignore my correction about the {s} repo; I pasted the wrong link. It is still {v}."],
    "return": ["Reverting the repo move: {s} code is back in {v} (rolling back the migration from {d})."],
    "retract": ["Retracting the {s} repo name I posted; it was a guess, so treat it as unknown."],
    "bait": "{s} code lives in {v}, while {s2} code lives in {v2}.",
    "hypo": "If we ever split {s} into a {v} repository, the build would need rework; just an idea, not planned.",
    "neardup": "An old fork called {v} exists for {s} experiments and is archived.",
    "quoted": "> Dead link from an old wiki: \"{s} source: {v}\".",
    "stale": "Stale ticket: consider renaming the {s} repo to {v} one day.",
}
T["svc_owner"] = {
    "assert": ["{s} is owned by {v}.", "{v} owns {s}."],
    "se": ["Update: ownership of {s} has passed to {v}.", "Ownership change: {v} now owns {s}."],
    "si": ["{v} approved every {s} deploy this week and is the first name on its escalation list."],
    "restate": ["{v} still owns {s}."],
    "reread": ["From an old service catalogue page: {s} owner {v}.", "{v} owns {s}."],
    "tset": ["Correction: {s} is actually owned by {v}."],
    "tvoid": ["Ignore my correction about who owns {s}; I misread the catalogue. {v} still owns it."],
    "return": ["Reverting the ownership change: {v} owns {s} again (rolling back the handover from {d})."],
    "retract": ["Retracting what I said about who owns {s}; it is unconfirmed, so treat the owner as unknown."],
    "bait": "{s} is owned by {v}, while {s2} is owned by {v2}.",
    "hypo": "If {v} ever picked up {s} as well, their on-call load would double; a hypothetical from the staffing chat.",
    "neardup": "{v} once paired on an {s} incident as a helper, which is why their name shows up in the old incident log.",
    "quoted": "> Unapproved ownership proposal: \"{s} -> {v}\".",
    "stale": "Old TODO: ask {v} whether they would ever take on {s}.",
}
T["host_region"] = {
    "assert": ["{s} runs in {v}.", "{s} is hosted in {v}."],
    "se": ["Update: {s} has been migrated to {v}.", "Region move complete: {s} now serves from {v}."],
    "si": ["The {s} dashboards show all of its traffic being served from {v}, and the pager routes there."],
    "restate": ["{s} is still hosted in {v}."],
    "reread": ["From the old runbook: {s} region {v}.", "{s} runs in {v}."],
    "tset": ["Correction: {s} actually runs in {v}."],
    "tvoid": ["Ignore my correction about {s}'s region; I looked at the wrong service. It is still in {v}."],
    "return": ["Reverting the region move: {s} is back in {v} (rolling back the migration from {d})."],
    "retract": ["Retracting the region I gave for {s}; it was unverified, so treat it as unknown."],
    "bait": "{s} runs in {v}, while {s2} runs in {v2}.",
    "hypo": "If {s} moved to {v}, the latency budget would break; that is a hypothetical from a capacity review.",
    "neardup": "{s} keeps a cold disaster-recovery snapshot in {v}, which does not serve any traffic.",
    "quoted": "> Deprecated capacity plan: \"{s} @ {v}\".",
    "stale": "Stale ticket: evaluate whether {s} could run in {v} someday.",
}
T["listen_port"] = {
    "assert": ["{s} listens on port {v}.", "{s} serves on port {v}."],
    "se": ["Update: {s} has switched to port {v}.", "Port change: {s} now listens on {v}."],
    "si": ["Health checks for {s} hit port {v} and the load balancer forwards there."],
    "restate": ["{s} is still on port {v}."],
    "reread": ["From an old deploy manifest: {s} port {v}.", "{s} listens on port {v}."],
    "tset": ["Correction: {s} actually listens on port {v}."],
    "tvoid": ["Ignore my port correction for {s}; wrong manifest. It is still on {v}."],
    "return": ["Reverting the port change: {s} is back on port {v} (rolling back the change from {d})."],
    "retract": ["Retracting the port I gave for {s}; it was wrong, so treat the port as unknown."],
    "bait": "{s} listens on port {v}, while {s2} listens on port {v2}.",
    "hypo": "If {s} were moved to port {v} it would clash with the sidecar; a what-if, nobody is doing it.",
    "neardup": "{s} exposes its debug metrics on port {v}, which is not the serving port.",
    "quoted": "> Example config from an old tutorial: \"{s}: port {v}\".",
    "stale": "Stale note: test whether port {v} would ever suit {s}.",
}
T["db_engine"] = {
    "assert": ["{s} stores its data in {v}.", "{s} uses {v} as its database."],
    "se": ["Update: {s} has been migrated onto {v}.", "Database change: {s} now runs on {v}."],
    "si": ["The {s} on-call runbook only covers {v} restores and the backups are {v} snapshots."],
    "restate": ["{s} is still on {v}."],
    "reread": ["From an old architecture doc: {s} on {v}.", "{s} uses {v} as its database."],
    "tset": ["Correction: {s} actually uses {v}."],
    "tvoid": ["Ignore my database correction for {s}; wrong diagram. It is still on {v}."],
    "return": ["Reverting the database migration: {s} is back on {v} (rolling back the change from {d})."],
    "retract": ["Retracting the database I named for {s}; it was unconfirmed, so treat it as unknown."],
    "bait": "{s} uses {v}, while {s2} uses {v2}.",
    "hypo": "If {s} ran on {v}, the cost model would change; this was a hypothetical in the architecture forum.",
    "neardup": "{s}'s analytics export lands in a separate {v} warehouse, which is not its primary store.",
    "quoted": "> Rejected design doc: \"{s} backed by {v}\".",
    "stale": "Stale spike ticket: benchmark {v} for {s} if there is ever time.",
}
T["cfg_max_rps"] = {
    "assert": ["The {s} caps traffic at {v} requests per second.", "The {s} sets a ceiling of {v} rps."],
    "se": ["Update: the {s} ceiling has been changed to {v} rps.", "Config change: the {s} now allows {v} requests per second."],
    "si": ["Load tests against the {s} plateau at exactly {v} requests per second, and alerts fire right there."],
    "restate": ["The {s} ceiling is still {v} rps."],
    "reread": ["From an old config dump: {s} ceiling {v} rps.", "The {s} caps traffic at {v} requests per second."],
    "tset": ["Correction: the {s} ceiling is actually {v} rps."],
    "tvoid": ["Ignore my correction to the {s} ceiling; wrong environment. It is still {v} rps."],
    "return": ["Reverting the config change: the {s} ceiling is {v} rps again (rolling back the change from {d})."],
    "retract": ["Retracting the {s} ceiling I quoted; it was not verified, so treat it as unknown."],
    "bait": "The {s} caps traffic at {v} rps, while the {s2} caps it at {v2} rps.",
    "hypo": "If the {s} allowed {v} rps the database would fall over; a thought experiment from the capacity review.",
    "neardup": "The staging copy of the {s} is set to {v} rps for load tests only.",
    "quoted": "> Sample value from vendor docs: \"{s} = {v} rps\".",
    "stale": "Stale ticket: consider trying {v} rps for the {s} someday.",
}
T["cfg_timeout_ms"] = {
    "assert": ["The {s} times out after {v} ms.", "The {s} uses a {v} ms timeout."],
    "se": ["Update: the {s} timeout has been changed to {v} ms.", "Config change: the {s} timeout is now {v} ms."],
    "si": ["Traces show calls under the {s} being cut off at {v} ms, consistently."],
    "restate": ["The {s} timeout is still {v} ms."],
    "reread": ["From an old config dump: {s} timeout {v} ms.", "The {s} times out after {v} ms."],
    "tset": ["Correction: the {s} timeout is actually {v} ms."],
    "tvoid": ["Ignore my timeout correction for the {s}; wrong file. It is still {v} ms."],
    "return": ["Reverting the timeout change: the {s} is back to {v} ms (rolling back the change from {d})."],
    "retract": ["Retracting the {s} timeout I posted; nobody verified it, so treat it as unknown."],
    "bait": "The {s} times out after {v} ms, while the {s2} times out after {v2} ms.",
    "hypo": "If the {s} timeout were {v} ms, retries would pile up; a hypothetical from the incident review.",
    "neardup": "The local dev override for the {s} uses {v} ms, which never ships.",
    "quoted": "> Vendor default from an old manual: \"{s} timeout {v} ms\".",
    "stale": "Stale ticket: maybe experiment with {v} ms for the {s}.",
}
# Derived keys: only an explicit derived statement exists (op=observe).
T["lead_office_city"] = {"assert": ["Whoever leads {s} has their office in {v}.", "The {s} lead sits in the {v} office."]}
T["lead_team_name"] = {"assert": ["Whoever leads {s} belongs to the {v} team.", "The {s} lead is on the {v} team."]}
T["owner_office_city"] = {"assert": ["Whoever owns {s} has their office in {v}.", "The {s} owner sits in the {v} office."]}
T["owner_team_name"] = {"assert": ["Whoever owns {s} is on the {v} team.", "The {s} owner belongs to the {v} team."]}

DISTRACTOR_KINDS = ["hypo", "neardup", "quoted", "stale"]

# Neutral filler: no values, no numbers, no month names, no entity other than
# people. Checked by tests (values never appear in filler segments).
FILLER_TOPICS = ["onboarding checklist", "incident retro", "planning doc", "design critique",
                 "naming guide", "test flake triage", "dependency upgrade", "release notes",
                 "dashboard cleanup", "accessibility audit", "code review backlog", "hiring loop",
                 "style guide", "lint rules", "postmortem template", "team charter",
                 "offsite agenda", "mentoring programme", "docs migration", "feedback survey"]
FILLER_TEMPLATES = [
    "{p} walked everyone through the {x}; follow-ups are in the tracker.",
    "We spent a while on the {x} and agreed to revisit it once more people have read it.",
    "{p} asked for more eyes on the {x} before the end of the week.",
    "Quick note on the {x}: the comments are mostly about wording, nothing blocking.",
    "{p} and {q} paired on the {x} and left a summary in the shared folder.",
    "The {x} discussion ran long, so the remaining items move to the next sync.",
    "Reminder that the {x} still needs an owner for the follow-up actions.",
    "{p} shared a short write-up about the {x} and asked for reactions.",
    "No decisions on the {x} yet; people want to sleep on it.",
    "{q} raised a fair point about the {x} that we should not lose track of.",
    "Coffee chat drifted into the {x} again, which is a sign it needs a proper session.",
    "{p} volunteered to tidy up the {x} and circulate a cleaner version.",
]
