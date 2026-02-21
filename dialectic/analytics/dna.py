# analytics/dna.py — Conversation DNA fingerprinting
"""
ARCHITECTURE: 6-dimensional fingerprint encoding conversation character.
WHY: Reduces complex conversation dynamics to a compact, comparable signature.
TRADEOFF: Lossy compression — captures shape, not content.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class ConversationDNA:
    """
    Six-dimensional fingerprint of a conversation's character.

    Each dimension is normalized 0.0–1.0. Together they encode
    the "shape" of a dialogue — its tension, pace, balance,
    intellectual depth, structural branching, and knowledge crystallization.
    """
    thread_id: UUID
    computed_at: datetime
    tension: float        # Disagreement ratio (COUNTEREXAMPLE + CLAIM density)
    velocity: float       # Messages per hour, normalized 0-1
    asymmetry: float      # Speaker balance (0=dominated by one speaker, 1=balanced)
    depth: float          # Structured type ratio + avg message length signal
    divergence: float     # Fork count relative to message count
    memory_density: float  # Memory operations per message count

    @property
    def fingerprint(self) -> str:
        """
        6-char hex encoding of the 6 dimensions.

        Each dimension maps to a 4-bit nibble (0-15), packed into
        3 bytes = 6 hex characters. Enables quick visual comparison.
        """
        dims = [
            self.tension, self.velocity, self.asymmetry,
            self.depth, self.divergence, self.memory_density,
        ]
        nibbles = [min(15, int(d * 15.999)) for d in dims]
        # Pack pairs of nibbles into bytes
        byte0 = (nibbles[0] << 4) | nibbles[1]
        byte1 = (nibbles[2] << 4) | nibbles[3]
        byte2 = (nibbles[4] << 4) | nibbles[5]
        return f"{byte0:02x}{byte1:02x}{byte2:02x}"

    @property
    def archetype(self) -> str:
        """
        Human-readable conversation type derived from dominant dimensions.

        ARCHITECTURE: Priority-ordered pattern matching on dimension thresholds.
        WHY: Gives users an intuitive label for conversation character.
        TRADEOFF: Discrete categories lose nuance; thresholds are heuristic.

        Archetypes:
          Crucible    — high tension, moderate+ velocity (heated debate)
          Forge       — high velocity + high tension (rapid-fire argument)
          Deep Dive   — high depth, low divergence (focused exploration)
          Rhizome     — high divergence (branching, exploratory)
          Symposium   — balanced asymmetry + moderate depth (structured dialogue)
          Open Field  — low structure across the board (free-form chat)
        """
        if self.tension > 0.6 and self.velocity > 0.5:
            return "Forge"
        if self.tension > 0.5:
            return "Crucible"
        if self.depth > 0.5 and self.divergence < 0.3:
            return "Deep Dive"
        if self.divergence > 0.4:
            return "Rhizome"
        if self.asymmetry > 0.6 and self.depth > 0.3:
            return "Symposium"
        return "Open Field"
