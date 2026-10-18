"""Clean A/B/C memory experiment primitives.

The package implements the three pre-registered memory policies, plus an
optional no-compression arm for a separate product comparison:

* ``window``        keep the system prompt, the task, and the newest complete
                    turns; drop older turns.
* ``summary``       same, plus a bounded evidence summary of the dropped turns.
* ``summary_search`` same summary policy plus a ``memory_search`` tool that
                    reads only the current run's transcript up to the current
                    step.
* ``full``          optional, not pre-registered: send the complete transcript
                    and do not enforce the prompt budget.

The three pre-registered arms share one prompt budget, one turn-aware history
representation, and one estimator.  The legacy ``HistoryManager`` is not used
here: it mixed
message-count and token policies, and its truncation dropped individual
messages, which loses the action/observation pairing that makes evidence
usable.

The public API is intentionally small:

    from minisweagent.memory.abc import MemoryAgent, MemoryAgentConfig

The experiment runner configures ``MemoryAgent`` from YAML; unit tests use the
policy classes directly.
"""

from .agent import MemoryAgent, MemoryAgentConfig, MemoryBudgetError
from .budget import (
    DEFAULT_RETRIEVAL_TOKENS,
    DEFAULT_SUMMARY_TOKENS,
    DEFAULT_TOTAL_TOKENS,
    BudgetError,
    PromptView,
    estimate_message_tokens,
    estimate_text_tokens,
    estimate_tokens,
    message_text,
)
from .conversation import Conversation, ConversationError, Segment, parse_conversation
from .policy import (
    FullPolicy,
    MemoryPolicy,
    PolicyLimits,
    SummaryPolicy,
    SummarySearchPolicy,
    WindowPolicy,
    build_policy,
)
from .replay import ReadEvent, ReplayStats, replay_transcript
from .search import MemorySearchTool, SearchContext, search_transcript
from .stats import PairedResult, mcnemar_exact, paired_result
from .summary import EvidenceSummary, build_evidence_summary

__all__ = [
    "BudgetError",
    "Conversation",
    "ConversationError",
    "DEFAULT_RETRIEVAL_TOKENS",
    "DEFAULT_SUMMARY_TOKENS",
    "DEFAULT_TOTAL_TOKENS",
    "EvidenceSummary",
    "FullPolicy",
    "MemoryAgent",
    "MemoryAgentConfig",
    "MemoryBudgetError",
    "MemoryPolicy",
    "MemorySearchTool",
    "PairedResult",
    "PolicyLimits",
    "PromptView",
    "ReadEvent",
    "ReplayStats",
    "SearchContext",
    "Segment",
    "SummaryPolicy",
    "SummarySearchPolicy",
    "WindowPolicy",
    "build_evidence_summary",
    "build_policy",
    "estimate_message_tokens",
    "estimate_text_tokens",
    "estimate_tokens",
    "mcnemar_exact",
    "message_text",
    "paired_result",
    "parse_conversation",
    "replay_transcript",
    "search_transcript",
]
