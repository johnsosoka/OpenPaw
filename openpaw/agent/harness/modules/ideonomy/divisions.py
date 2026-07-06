"""The 28 curated ideonomic divisions — pure data, no logic.

Ideonomy is Patrick Gunkel's "science of ideas" (https://ideonomy.mit.edu):
a taxonomy of ~235 universal conceptual divisions (ANALOGIES, CAUSES,
PARADOXES, ...) usable as reasoning lenses on any problem. This module ports
the 28-division curated subset — each enriched with keywords, a core
question, and guiding questions — from the MIT-licensed reference
implementation https://github.com/Morpheis/ideonomy-engine
(``src/data/divisions.ts``, v0.2.0), with attribution to both.

``id`` is Gunkel's division number; ``binomen`` is his Latin name for the
division; ``group`` is the thematic grouping used by the reference engine.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Division:
    """One ideonomic division, usable as a reasoning lens.

    Attributes:
        id: Gunkel's division number (within his 235-division taxonomy).
        theme: Division name, e.g. "ANALOGIES".
        binomen: Gunkel's Latin name for the division.
        group: Thematic group (understanding, causation, change, ...).
        keywords: Lowercase scoring terms for lens selection.
        core_question: The single question this lens asks of a problem.
        guiding_questions: Sub-questions to think through against the task.
    """

    id: int
    theme: str
    binomen: str
    group: str
    keywords: tuple[str, ...]
    core_question: str
    guiding_questions: tuple[str, ...]


DIVISIONS: tuple[Division, ...] = (
    # --- UNDERSTANDING (what is it?) ---
    Division(
        id=6,
        theme="ANALOGIES",
        binomen="Icelology",
        group="understanding",
        keywords=("similar", "like", "compare", "parallel", "metaphor", "resembles", "equivalent", "maps to"),
        core_question="What is this fundamentally like?",
        guiding_questions=(
            "What natural systems exhibit similar behavior or structure?",
            "What problems in other domains have been solved with analogous approaches?",
            "What metaphor best captures the essence of this situation?",
            "Where does the analogy break down, and what does that reveal?",
            "What would a biologist/physicist/architect/musician see in this problem?",
        ),
    ),
    Division(
        id=7,
        theme="ANALYSES",
        binomen="Merismology",
        group="understanding",
        keywords=("break down", "decompose", "parts", "components", "dissect", "examine", "structure", "anatomy"),
        core_question="What are the constituent parts, and how do they relate?",
        guiding_questions=(
            "What are the irreducible components of this problem?",
            "Which part, if removed, would change the nature of the whole?",
            "What hidden dependencies exist between the parts?",
            "At what level of granularity does the most useful analysis occur?",
        ),
    ),
    Division(
        id=29,
        theme="CONCEPTS",
        binomen="Ennoology",
        group="understanding",
        keywords=("define", "meaning", "idea", "notion", "abstract", "concept", "essence", "what is"),
        core_question="What exactly do we mean, and what concepts are we really working with?",
        guiding_questions=(
            "Are there ambiguous terms that different people interpret differently?",
            "What concept is actually central vs. what we assume is central?",
            "What new concept might we need to invent to think about this clearly?",
            "What would Gunkel's 'binomen' be for this idea — what is its true name?",
        ),
    ),
    Division(
        id=163,
        theme="PERSPECTIVES",
        binomen="Apopsology",
        group="understanding",
        keywords=("viewpoint", "angle", "frame", "lens", "stakeholder", "see", "perceive", "interpret"),
        core_question="How does this look from radically different vantage points?",
        guiding_questions=(
            "Who sees this problem completely differently, and why?",
            "What perspective would make this obvious or trivial?",
            "What would this look like in 100 years? 1000 years?",
            "What would an alien intelligence notice that we miss?",
        ),
    ),
    # --- CAUSATION (why?) ---
    Division(
        id=17,
        theme="CAUSES",
        binomen="Etiology",
        group="causation",
        keywords=("why", "because", "reason", "root cause", "origin", "trigger", "source", "driver"),
        core_question="Why does this happen, and what are the real causes?",
        guiding_questions=(
            "What is the proximate cause vs. the ultimate cause?",
            "What causes are we assuming that might be wrong?",
            "What feedback loops amplify or dampen the causes?",
            "If you removed each cause one by one, which one actually matters?",
        ),
    ),
    Division(
        id=19,
        theme="CHAINS-OF-CONSEQUENCES",
        binomen="Anyormology",
        group="causation",
        keywords=("consequence", "result", "cascade", "domino", "ripple", "downstream", "impact", "then what"),
        core_question="What cascading consequences follow, and how far do they reach?",
        guiding_questions=(
            "What is the second-order effect that nobody is discussing?",
            "Where does the chain of consequences cross into a different domain?",
            "What unintended consequences are most likely?",
            "At what point does the cascade become unpredictable?",
        ),
    ),
    Division(
        id=153,
        theme="ORIGINS",
        binomen="Archology",
        group="causation",
        keywords=("beginning", "genesis", "start", "source", "where from", "history", "root", "seed"),
        core_question="Where did this actually begin, and what was the original seed?",
        guiding_questions=(
            "What was the earliest recognizable form of this thing?",
            "What conditions made its emergence possible?",
            "Could it have originated differently, and would that change its nature?",
            "What has been forgotten about its origins that still shapes it?",
        ),
    ),
    Division(
        id=13,
        theme="BADS",
        binomen="Cacology",
        group="causation",
        keywords=("fail", "wrong", "risk", "danger", "problem", "flaw", "weakness", "pitfall", "mistake"),
        core_question="What can go wrong, and what is already going wrong that we're not seeing?",
        guiding_questions=(
            "What is the worst realistic outcome?",
            "What failure mode is everyone ignoring because it's uncomfortable?",
            "Where are the single points of failure?",
            "What would a hostile adversary exploit?",
        ),
    ),
    # --- CHANGE (how does it move?) ---
    Division(
        id=21,
        theme="CHANGES",
        binomen="Tropology",
        group="change",
        keywords=("evolve", "transform", "shift", "adapt", "develop", "progress", "transition", "trend"),
        core_question="How is this changing, and where is it heading?",
        guiding_questions=(
            "What is changing faster than expected? Slower?",
            "What appears stable but is actually on the verge of transformation?",
            "What driving forces are accelerating or decelerating the change?",
            "What phase of its lifecycle is this in?",
        ),
    ),
    Division(
        id=44,
        theme="CYCLES",
        binomen="Nostology",
        group="change",
        keywords=("cycle", "repeat", "periodic", "rhythm", "loop", "oscillate", "recur", "season"),
        core_question="What cycles, rhythms, or recurring patterns are at play?",
        guiding_questions=(
            "What has happened before that's happening again?",
            "What is the natural period of this cycle?",
            "Are we at a peak, trough, or inflection point?",
            "What would break the cycle — and should we want to break it?",
        ),
    ),
    Division(
        id=127,
        theme="LIMITATIONS",
        binomen="Horology",
        group="change",
        keywords=("limit", "constraint", "boundary", "ceiling", "barrier", "bottleneck", "cap", "threshold"),
        core_question="What are the real limits, and which ones are actually movable?",
        guiding_questions=(
            "Which constraints are physical/fundamental vs. conventional/assumed?",
            "What becomes possible if the biggest constraint is removed?",
            "What are we treating as a limit that's really just a current state?",
            "What limit are we approaching that we haven't noticed yet?",
        ),
    ),
    Division(
        id=219,
        theme="TRANSFORMATIONS",
        binomen="Diaplastology",
        group="change",
        keywords=("transform", "convert", "reshape", "metamorphose", "transmute", "reframe", "pivot"),
        core_question="What transformations are possible, and what would fundamentally change the nature of this?",
        guiding_questions=(
            "What would this look like if its core assumption were inverted?",
            "What minimal change would produce the maximal transformation?",
            "What transformation has already happened that we haven't recognized?",
            "What is preventing the natural transformation from occurring?",
        ),
    ),
    # --- STRUCTURE (how is it organized?) ---
    Division(
        id=96,
        theme="HIERARCHIES",
        binomen="Climology",
        group="structure",
        keywords=("hierarchy", "level", "layer", "rank", "order", "above", "below", "nested", "priority"),
        core_question="What hierarchies exist here, and are they the right ones?",
        guiding_questions=(
            "What levels of abstraction are most useful for thinking about this?",
            "Is the current hierarchy natural or imposed? By whom?",
            "What happens if you flatten the hierarchy? Deepen it?",
            "What sits at the top that shouldn't, or at the bottom that should be higher?",
        ),
    ),
    Division(
        id=26,
        theme="COMBINATIONS",
        binomen="Mixology",
        group="structure",
        keywords=("combine", "mix", "merge", "integrate", "synthesize", "hybrid", "blend", "fusion"),
        core_question="What combinations haven't been tried, and what emerges from unlikely pairings?",
        guiding_questions=(
            "What two things, if combined, would create something genuinely new?",
            "What combinations are everyone doing that have become stale?",
            "What elements resist combination, and why?",
            "What is the 'minimum viable combination' that produces the desired emergent property?",
        ),
    ),
    Division(
        id=160,
        theme="PATTERNS",
        binomen="Digmology",
        group="structure",
        keywords=("pattern", "recur", "motif", "template", "regularity", "structure", "shape", "form"),
        core_question="What patterns are present, and what do they predict?",
        guiding_questions=(
            "What pattern is visible at one scale but invisible at another?",
            "What pattern from a completely different domain applies here?",
            "What apparent pattern is actually coincidence?",
            "What would the pattern predict happens next?",
        ),
    ),
    Division(
        id=146,
        theme="NETWORKS",
        binomen="Dictyology",
        group="structure",
        keywords=("network", "connection", "graph", "link", "node", "web", "relationship", "topology"),
        core_question="What is the network structure, and where are the critical connections?",
        guiding_questions=(
            "What are the most connected nodes, and what happens if they fail?",
            "What connections are missing that should exist?",
            "Is this a small-world, scale-free, or random network?",
            "Where are the bridges between otherwise disconnected clusters?",
        ),
    ),
    Division(
        id=209,
        theme="SYSTEMS",
        binomen="Systemology",
        group="structure",
        keywords=("system", "feedback", "loop", "emergent", "complex", "adaptive", "ecosystem", "holistic"),
        core_question="What system dynamics are at play, and what emerges from the whole?",
        guiding_questions=(
            "What feedback loops — positive or negative — are driving behavior?",
            "What properties emerge from the system that no component has alone?",
            "Where are the leverage points where small changes have big effects?",
            "What is the system optimizing for, and is that what we want?",
        ),
    ),
    # --- ALTERNATIVES (what else?) ---
    Division(
        id=3,
        theme="ALTERNATIVES",
        binomen="Allagology",
        group="alternatives",
        keywords=("alternative", "option", "instead", "other way", "different approach", "what if", "choose"),
        core_question="What alternatives exist that we haven't considered?",
        guiding_questions=(
            "What approach would someone from a completely different field take?",
            "What option are we dismissing too quickly?",
            "What is the 'do nothing' alternative, and what happens then?",
            "What alternative was tried before and failed — and has anything changed since?",
        ),
    ),
    Division(
        id=151,
        theme="OPPOSITES",
        binomen="Enantiology",
        group="alternatives",
        keywords=("opposite", "reverse", "inverse", "contrary", "antithesis", "negate", "flip", "contrast"),
        core_question="What is the opposite, and what can we learn from inverting our assumptions?",
        guiding_questions=(
            "What if we wanted the exact opposite outcome — what would we do?",
            "What is the shadow or dark twin of our current approach?",
            "What truth is hiding in the position we most disagree with?",
            "What apparent opposites are actually complementary?",
        ),
    ),
    Division(
        id=119,
        theme="INVERSIONS",
        binomen="Simomology",
        group="alternatives",
        keywords=("invert", "reverse", "flip", "upside down", "backwards", "turn around", "mirror"),
        core_question="What happens when we invert or reverse the problem?",
        guiding_questions=(
            "What if we solved for the opposite of what we want and then negated?",
            "What becomes visible when you read the situation backwards?",
            "What would the solution look like if we started from the end?",
            "What assumption, if inverted, changes everything?",
        ),
    ),
    Division(
        id=73,
        theme="EXCELLENCES",
        binomen="Aristology",
        group="alternatives",
        keywords=("ideal", "perfect", "best", "excellence", "optimal", "gold standard", "aspire", "benchmark"),
        core_question="What would perfection look like, and what can we learn from the ideal?",
        guiding_questions=(
            "If there were no constraints, what would the ideal solution be?",
            "What existing example comes closest to excellence here?",
            "What quality separates good from excellent in this domain?",
            "What would we never compromise on if we were building this right?",
        ),
    ),
    # --- CONTEXT (where does it sit?) ---
    Division(
        id=23,
        theme="CIRCUMSTANCES",
        binomen="Symphorology",
        group="context",
        keywords=("context", "circumstance", "condition", "environment", "situation", "when", "where", "setting"),
        core_question="What circumstances and conditions make this the way it is?",
        guiding_questions=(
            "What environmental factors are we taking for granted?",
            "How would different circumstances change the entire problem?",
            "What circumstance is temporary but being treated as permanent?",
            "What context does the other side have that we lack?",
        ),
    ),
    Division(
        id=27,
        theme="COMMONALITIES",
        binomen="Metochology",
        group="context",
        keywords=("common", "shared", "universal", "same", "overlap", "mutual", "consensus", "agree"),
        core_question="What is shared or universal here that we might be overlooking?",
        guiding_questions=(
            "What do all instances of this problem have in common?",
            "What is the underlying commonality between seemingly different approaches?",
            "What assumption does everyone share — and is it valid?",
            "What common ground exists between opposing positions?",
        ),
    ),
    Division(
        id=50,
        theme="DIFFERENCES",
        binomen="Heterology",
        group="context",
        keywords=("different", "distinct", "unique", "varies", "diverge", "gap", "contrast", "separate"),
        core_question="What are the critical differences, and which ones actually matter?",
        guiding_questions=(
            "What difference is everyone noticing that's actually irrelevant?",
            "What subtle difference is being ignored that's actually decisive?",
            "What makes this instance different from every other?",
            "Where is the line between 'different type' and 'different degree'?",
        ),
    ),
    # --- DEEPER THINKING ---
    Division(
        id=81,
        theme="FIRST PRINCIPLES",
        binomen="Archelogy",
        group="deeper thinking",
        keywords=("fundamental", "axiom", "base", "foundation", "ground truth", "first principles", "from scratch"),
        core_question="What are the first principles, and what can we derive from them alone?",
        guiding_questions=(
            "If we threw out all assumptions and started from physical/logical bedrock, what would we build?",
            "What first principle is everyone citing but nobody has actually verified?",
            "What first principles conflict with each other here?",
            "What new first principle might we be discovering?",
        ),
    ),
    Division(
        id=157,
        theme="PARADOXES",
        binomen="Paradoxology",
        group="deeper thinking",
        keywords=("paradox", "contradiction", "impossible", "both true", "tension", "dilemma", "ironic"),
        core_question="What paradoxes or contradictions exist, and what do they reveal?",
        guiding_questions=(
            "What two things are both true that seem like they can't both be true?",
            "What apparent contradiction dissolves when you reframe the question?",
            "What paradox is the system trying to resolve, possibly poorly?",
            "What would it mean to hold both sides of the contradiction simultaneously?",
        ),
    ),
    Division(
        id=8,
        theme="ANOMALIES",
        binomen="Xenology",
        group="deeper thinking",
        keywords=("anomaly", "exception", "outlier", "unusual", "unexpected", "deviant", "strange", "surprising"),
        core_question="What anomalies or exceptions exist, and what do they tell us?",
        guiding_questions=(
            "What doesn't fit the pattern, and why?",
            "What exception might actually be the new rule emerging?",
            "What anomaly has everyone noticed but nobody has explained?",
            "What would we learn if we studied the outliers instead of the average?",
        ),
    ),
    Division(
        id=174,
        theme="PROCESSES",
        binomen="Sisology",
        group="deeper thinking",
        keywords=("process", "step", "sequence", "workflow", "procedure", "flow", "pipeline", "stages"),
        core_question="What processes are at work, and where do they break down?",
        guiding_questions=(
            "What step in the process adds the most value? The least?",
            "Where does the process create bottlenecks or waste?",
            "What process is happening implicitly that should be made explicit?",
            "What would a zero-step process look like — can we eliminate the process entirely?",
        ),
    ),
)
