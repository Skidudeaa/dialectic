// Step 4 — TradingView integration.
//
// The point: Pine alerts can mutate the live graph. The illustration shows
// the signed-webhook flow as a left-to-right pipeline so the security model
// (HMAC, nonce, ts) is visible — operators care about that.

import StepFrame from "../StepFrame";
import TryThis from "../TryThis";

function WebhookFlow() {
  return (
    <div>
      <div className="flex items-center justify-between gap-2 font-mono text-[10px]">
        <div className="flex-1 text-center bg-elevated rounded p-2 border border-border">
          <div className="text-text-primary">TradingView</div>
          <div className="text-text-dim text-[9px]">Pine alert</div>
        </div>
        <span className="text-text-dim">→</span>
        <div className="flex-1 text-center bg-elevated rounded p-2 border border-border">
          <div className="text-text-primary">Relay</div>
          <div className="text-text-dim text-[9px]">HMAC signs body</div>
        </div>
        <span className="text-text-dim">→</span>
        <div className="flex-1 text-center bg-amber/10 rounded p-2 border border-amber/40">
          <div className="text-amber">Webhook</div>
          <div className="text-text-dim text-[9px]">verify + mutate</div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-1.5 font-mono text-[10px]">
        <div className="bg-surface rounded p-1.5 border border-border/60">
          <span className="text-teal">incrementClosesObserved</span>
          <span className="text-text-dim ml-1">→ price node</span>
        </div>
        <div className="bg-surface rounded p-1.5 border border-border/60">
          <span className="text-teal">setNodeState</span>
          <span className="text-text-dim ml-1">→ event node</span>
        </div>
        <div className="bg-surface rounded p-1.5 border border-border/60">
          <span className="text-teal">setProbability</span>
          <span className="text-text-dim ml-1">→ event node</span>
        </div>
        <div className="bg-surface rounded p-1.5 border border-border/60">
          <span className="text-teal">setCurrent</span>
          <span className="text-text-dim ml-1">→ price node</span>
        </div>
      </div>
    </div>
  );
}

export default function TradingViewStep() {
  return (
    <StepFrame
      title="Pine alerts that move the graph, not just your inbox."
      lede={
        <>
          Wire a TradingView alert to a node and it mutates the snapshot
          directly — the chat rooms get a system message, the cascade
          recomputes, the LLMs see the new state. Every webhook hit is signed,
          rate-limited, and audited.
        </>
      }
      illustration={<WebhookFlow />}
      bullets={[
        {
          title: "Four typed mutation ops",
          body: "Strict node-type gates — a price-node op can't touch an event node, and vice versa.",
        },
        {
          title: "HMAC-SHA256 signatures + nonce replay store",
          body: "±300s timestamp window, 60 req/min per IP, 8 KiB body cap. Bad signature = nothing happens.",
        },
        {
          title: "Bindings panel + recent alerts feed",
          body: "See every Pine alert wired to your books, fire counts, and the last 20 webhook hits color-coded by status.",
        },
      ]}
      tryThis={
        <TryThis
          intro={
            <>
              Wire this to a Brent chart on TradingView — three closes
              above $115 promote the brent node to fired and open the
              XOP gate. The binding{" "}
              <span className="font-mono text-amber">
                brent-persistence-close-above-115
              </span>{" "}
              is already seeded, so the message body just needs to match.
            </>
          }
          snippets={[
            {
              label: "Pine alertcondition recipe",
              multiline: true,
              text: `alertcondition(close > 115 and close > close[1] and close[1] > close[2],
  "brent-persistence",
  "{\\"book\\":\\"iran-hormuz-graph\\",\\"bindingId\\":\\"brent-persistence-close-above-115\\",\\"value\\":\\"{{close}}\\"}")`,
              caption: "Paste into a Pine script on a Brent (CL1!) chart, then create an alert with webhook URL pointed at /api/tradingview/webhook.",
              ariaLabel: "Copy Pine alertcondition recipe for brent persistence",
            },
            {
              label: "Sign + send a test hit from the CLI",
              text: "TV_WEBHOOK_SECRET=$TV_WEBHOOK_SECRET python3 tools/bridge/sign_tv_alert.py --book iran-hormuz-graph --binding brent-persistence-close-above-115 --value 116.20",
              caption: "Prints a ready-to-run signed curl command — verifies the round-trip without waiting for a real close.",
              ariaLabel: "Copy CLI command to sign and send a test TradingView alert",
            },
          ]}
        />
      }
    />
  );
}
