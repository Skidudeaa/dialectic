// Step 2 — Chat panel.
//
// The thing analysts spend most of their day in. Mini transcript shows a
// human → @claude → @compare arc so the social + LLM affordances are
// obvious in one glance.

import StepFrame from "../StepFrame";
import TryThis from "../TryThis";

function MiniTranscript() {
  return (
    <div className="font-mono text-[11px] leading-relaxed space-y-1.5">
      <div>
        <span className="text-amber">amo</span>
        <span className="text-text-dim ml-2">@claude</span>
        <span className="text-text-primary ml-1">
          brent just broke 115 — does that promote the persistence node?
        </span>
      </div>
      <div className="pl-2 border-l-2 border-teal/50">
        <span className="text-teal">claude</span>
        <span className="text-text-muted ml-2">
          Not yet — needs 3 daily closes above 115. This is close 1 of 3.
          Confluence on em-stress is 1.67 → bias is right but the trigger
          hasn't fully fired.
        </span>
      </div>
      <div>
        <span className="text-amber">dan</span>
        <span className="text-text-primary ml-2">/brief</span>
      </div>
      <div className="pl-2 border-l-2 border-text-dim">
        <span className="text-text-dim">system</span>
        <span className="text-text-muted ml-2">
          Morning brief — iran-hormuz: 2 nodes fired, 1 approaching.
          Cascade: transmission STARTING. Open trade: TRD-XOP-HORMUZ at $94.
        </span>
      </div>
    </div>
  );
}

export default function ChatPanelStep() {
  return (
    <StepFrame
      title="Argue with another human and three LLMs at once."
      lede={
        <>
          Each room is tied to a thesis book. Claude, GPT, and Gemini all see
          the live graph state when they answer — node states, confluence,
          countdowns — so you never paste context.
        </>
      }
      illustration={<MiniTranscript />}
      bullets={[
        {
          title: "Mention models inline",
          body: (
            <>
              <span className="kbd">@claude</span>{" "}
              <span className="kbd">@gpt</span>{" "}
              <span className="kbd">@gemini</span> — or{" "}
              <span className="kbd">@compare</span> to run all three and pick
              the answer you trust.
            </>
          ),
        },
        {
          title: "Slash commands inject context",
          body: (
            <>
              <span className="kbd">/brief</span>{" "}
              <span className="kbd">/thesis</span>{" "}
              <span className="kbd">/diff</span>{" "}
              <span className="kbd">/predict</span>{" "}
              <span className="kbd">/watchlist</span> drop live snapshots
              right into the room.
            </>
          ),
        },
        {
          title: "Pin what matters, export when done",
          body: "Hover a message to pin it; export the full transcript as markdown for post-mortems.",
        },
      ]}
      shortcut={
        <>
          <span className="kbd">Enter</span> to send,{" "}
          <span className="kbd">Shift+Enter</span> for newline
        </>
      }
      tryThis={
        <TryThis
          intro={
            <>
              Three prompts that earn their keep on day one. Pick one,
              paste it into the room tied to the matching book.
            </>
          }
          snippets={[
            {
              label: "Confluence question — iran-hormuz room",
              text: "@claude given Brent at $90 vs the $115 persistence threshold, is the XOP-HORMUZ entry still on, or did we miss it?",
              ariaLabel: "Copy Claude prompt about XOP entry",
            },
            {
              label: "Devil's advocate — iran-hormuz room",
              text: "@compare argue both sides: should we trim the planting-miss countdown trade with 17d to go, or hold for the full window?",
              ariaLabel: "Copy compare prompt about planting-miss",
            },
            {
              label: "Slash command — any room",
              text: "/brief",
              caption: "Drops this morning's snapshot summary into the room — node states, cascade phase, open trades.",
              ariaLabel: "Copy /brief slash command",
            },
          ]}
        />
      }
    />
  );
}
