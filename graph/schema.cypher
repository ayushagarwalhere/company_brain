// Company Brain graph schema (draft, Phase 1 will finalise properties).
// Idempotent: every writer uses MERGE on the indexed `id` property, so re-ingesting creates no duplicates.
//
// Nodes:  Person, Message, Ticket, PullRequest, Feature, Requirement, Decision, Sprint
// Edges:
//   (Person)-[:POSTED]->(Message)
//   (Person)-[:AUTHORED]->(Ticket|PullRequest)
//   (Ticket|PullRequest)-[:ASSIGNED_TO]->(Person)
//   (Message|Ticket|PullRequest)-[:ABOUT]->(Feature)
//   (Ticket)-[:STATES {at}]->(Requirement)
//   (Message|Decision)-[:CHANGES {at}]->(Requirement)
//   (PullRequest)-[:IMPLEMENTS]->(Requirement)
//   (Requirement|Decision)-[:SUPERSEDES]->(Requirement|Decision)
//   (Ticket|PullRequest)-[:IN_SPRINT]->(Sprint)

CREATE INDEX FOR (n:Person) ON (n.id);
CREATE INDEX FOR (n:Message) ON (n.id);
CREATE INDEX FOR (n:Ticket) ON (n.id);
CREATE INDEX FOR (n:PullRequest) ON (n.id);
CREATE INDEX FOR (n:Feature) ON (n.id);
CREATE INDEX FOR (n:Requirement) ON (n.id);
CREATE INDEX FOR (n:Decision) ON (n.id);
CREATE INDEX FOR (n:Sprint) ON (n.id);
CREATE INDEX FOR (n:Message) ON (n.ts);
