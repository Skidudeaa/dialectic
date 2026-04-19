import { Link } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Clock,
  GitFork,
  Sparkles,
  Wrench,
} from "lucide-react";

import {
  EXTERNAL_LINKS,
  FEATURES,
  ROADMAP,
  USE_CASES,
} from "../lib/welcome";
import HeroGraph from "../components/welcome/HeroGraph";
import WorkspaceDiagram from "../components/welcome/WorkspaceDiagram";
import FeatureCard from "../components/welcome/FeatureCard";
import ArchitectureDiagram from "../components/welcome/ArchitectureDiagram";
import SectionToc from "../components/welcome/SectionToc";
import CookbookSection from "../components/welcome/CookbookSection";
import NegativesSection from "../components/welcome/NegativesSection";

// Welcome — the evergreen guide to Trading Desk. Always reachable from
// the dashboard "?" link. Pairs with Team A's first-login modal tour;
// where the tour is fast, this page is deep.
//
// Layout: a sticky left rail (TOC) + a single scrollable column. The page
// breathes more than the dashboard but keeps the same dark-terminal
// palette, mono headlines, amber accent.

export default function Welcome() {
  return (
    <div className="min-h-screen bg-void text-text-primary">
      {/* Subtle ambient gradient — keeps the page from feeling flat without
          stealing attention from content. Pointer-events-none so it never
          blocks clicks. */}
      <div
        className="fixed inset-0 pointer-events-none"
        aria-hidden="true"
        style={{
          background:
            "radial-gradient(ellipse at 20% 0%, rgba(212,168,67,0.05) 0%, transparent 50%), radial-gradient(ellipse at 80% 90%, rgba(45,212,191,0.04) 0%, transparent 55%)",
        }}
      />

      {/* Top bar */}
      <header className="sticky top-0 z-20 backdrop-blur bg-void/80 border-b border-border">
        <div className="max-w-6xl mx-auto px-4 lg:px-6 h-12 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-amber" aria-hidden="true" />
            <span className="text-sm font-mono font-semibold text-amber leading-none">
              tradingDesk
            </span>
            <span className="text-text-dim font-mono text-xs leading-none">/ welcome</span>
          </div>
          <Link
            to="/"
            className="btn-secondary inline-flex items-center gap-1.5"
            aria-label="Back to the dashboard"
          >
            <ArrowLeft size={12} aria-hidden="true" />
            <span>Dashboard</span>
          </Link>
        </div>
      </header>

      <div className="relative max-w-6xl mx-auto px-4 lg:px-6 py-8 lg:py-12 flex gap-8">
        <SectionToc />

        <main className="flex-1 min-w-0 space-y-20">
          {/* ─────────────────────────────────────────────── HERO */}
          <section
            id="hero"
            aria-labelledby="hero-title"
            className="min-h-[calc(100vh-12rem)] flex flex-col justify-center"
          >
            <div className="inline-flex items-center gap-1.5 mb-4">
              <span className="badge bg-amber/15 text-amber">causal · live · two-analyst</span>
            </div>
            <h1
              id="hero-title"
              className="font-mono text-4xl md:text-6xl font-bold text-text-primary leading-[1.05] tracking-tight mb-4"
            >
              Trade the chain,
              <br />
              <span className="text-amber">not the headline.</span>
            </h1>
            <p className="text-base md:text-lg text-text-muted max-w-xl leading-relaxed mb-8">
              Trading Desk is a causal reasoning engine for macro trading. Theses are
              graphs. Shocks propagate. State, scenarios, and confluence are computed —
              not vibed.
            </p>

            <div className="bg-surface border border-border rounded-md p-4 mb-6">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] uppercase tracking-widest text-text-dim font-mono">
                  iran-hormuz-graph · live
                </span>
                <span className="text-[10px] font-mono text-text-muted inline-flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse-amber" />
                  propagating
                </span>
              </div>
              <HeroGraph />
            </div>

            <div className="flex flex-wrap gap-2">
              <a href="#what" className="btn-primary inline-flex items-center gap-1.5">
                <span>Take the tour</span>
                <ArrowRight size={12} aria-hidden="true" />
              </a>
              <Link to="/" className="btn-secondary">
                Open the dashboard
              </Link>
            </div>
          </section>

          {/* ─────────────────────────────────────────────── WHAT */}
          <section id="what" aria-labelledby="what-title">
            <h2 id="what-title" className="font-mono text-2xl text-text-primary mb-4">
              What this is
            </h2>
            <div className="space-y-4 max-w-3xl text-sm md:text-base text-text-muted leading-relaxed">
              <p>
                Most trading software is reactive. Prices move, alerts fire, you
                interpret. Macro is different — the move you care about is three steps
                downstream of a shock that already happened. By the time the price tells
                you, the chain is fully priced in.
              </p>
              <p>
                Trading Desk models the world the way macro actually transmits: as a
                directed graph of causal channels. Oil shock to diesel to freight to
                employment to demand destruction. Each node has thresholds. Each edge
                has a mechanism, a lag, an amplification factor. When upstream fires,
                downstream is told.
              </p>
              <p className="text-text-primary">
                The result is a desk that lets you anticipate, not chase. Two theses
                run live today —{" "}
                <span className="font-mono text-amber">iran-hormuz-graph</span> and{" "}
                <span className="font-mono text-amber">trump-tariffs-graph</span> — each
                with its own room, its own portfolio, its own running confluence.
              </p>
            </div>
          </section>

          {/* ─────────────────────────────────────────────── WORKSPACE */}
          <section id="workspace" aria-labelledby="workspace-title">
            <h2 id="workspace-title" className="font-mono text-2xl text-text-primary mb-2">
              The 5-panel workspace
            </h2>
            <p className="text-sm text-text-muted max-w-2xl mb-6">
              The dashboard is dense on purpose. Five panels, no modal-soup, every
              piece of context one glance away. Hover the layout to see what each panel
              owns.
            </p>
            <WorkspaceDiagram />
          </section>

          {/* ─────────────────────────────────────────────── FEATURES */}
          <section
            id="engine"
            aria-labelledby="features-title"
            className="space-y-3"
          >
            <div className="flex items-baseline justify-between flex-wrap gap-2">
              <h2 id="features-title" className="font-mono text-2xl text-text-primary">
                Features in depth
              </h2>
              <span className="text-[10px] font-mono uppercase tracking-widest text-text-dim">
                expand any card
              </span>
            </div>
            <p className="text-sm text-text-muted max-w-2xl mb-2">
              Each card collapses to a one-line summary. Click to read what's actually
              behind it — schemas, thresholds, the small architectural choices that
              matter.
            </p>
            {/* Anchors for the data/tradingview/etc TOC entries; they live
                inside the same scrollable feature list. */}
            <div className="space-y-3">
              {FEATURES.map((f) => (
                <div key={f.id} id={f.id}>
                  <FeatureCard feature={f} />
                </div>
              ))}
            </div>
          </section>

          {/* ─────────────────────────────────────────────── USE CASES */}
          <section id="stories" aria-labelledby="stories-title">
            <h2 id="stories-title" className="font-mono text-2xl text-text-primary mb-2">
              A day on the desk
            </h2>
            <p className="text-sm text-text-muted max-w-2xl mb-6">
              Concrete, not aspirational. These are the moments the system is built
              for.
            </p>
            <ol className="grid md:grid-cols-2 gap-4">
              {USE_CASES.map((uc) => (
                <li
                  key={uc.id}
                  className="bg-surface border border-border rounded-md p-4 flex flex-col"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Clock size={12} className="text-amber" aria-hidden="true" />
                    <span className="text-[10px] uppercase tracking-widest font-mono text-amber">
                      {uc.time}
                    </span>
                  </div>
                  <h3 className="text-sm font-semibold text-text-primary mb-2">
                    {uc.title}
                  </h3>
                  <p className="text-xs text-text-muted leading-relaxed">{uc.body}</p>
                </li>
              ))}
            </ol>
          </section>

          {/* ─────────────────────────────────────────────── COOKBOOK */}
          <CookbookSection />

          {/* ─────────────────────────────────────────────── WHAT THIS ISN'T */}
          <NegativesSection />

          {/* ─────────────────────────────────────────────── ARCHITECTURE */}
          <section id="architecture" aria-labelledby="architecture-title">
            <h2 id="architecture-title" className="font-mono text-2xl text-text-primary mb-2">
              Architecture
            </h2>
            <p className="text-sm text-text-muted max-w-2xl mb-6">
              One Python engine, one FastAPI backend, one React SPA, one Dialectic
              service, one droplet. Hover a layer to see what lives where.
            </p>
            <ArchitectureDiagram />
          </section>

          {/* ─────────────────────────────────────────────── ROADMAP */}
          <section id="roadmap" aria-labelledby="roadmap-title">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles size={16} className="text-teal" aria-hidden="true" />
              <h2 id="roadmap-title" className="font-mono text-2xl text-text-primary">
                What's coming
              </h2>
            </div>
            <p className="text-sm text-text-muted max-w-2xl mb-6">
              Drawn from{" "}
              <span className="font-mono text-text-primary">
                tradingdesk-web-ui-v2-spec.md
              </span>
              . Direction, not promises.
            </p>
            <div className="space-y-2">
              {ROADMAP.map((r) => (
                <article
                  key={r.id}
                  className="bg-surface border border-border rounded-md p-4 flex gap-4"
                >
                  <div className="shrink-0 w-9 h-9 rounded grid place-items-center bg-teal/10 text-teal">
                    <Wrench size={16} strokeWidth={1.5} aria-hidden="true" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-3 mb-1 flex-wrap">
                      <h3 className="text-sm font-semibold text-text-primary">
                        {r.title}
                      </h3>
                      <span className="text-[10px] font-mono text-text-dim uppercase tracking-widest">
                        {r.spec}
                      </span>
                    </div>
                    <p className="text-xs text-text-muted leading-relaxed">{r.body}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>

          {/* ─────────────────────────────────────────────── LINKS */}
          <section id="links" aria-labelledby="links-title" className="pb-8">
            <h2 id="links-title" className="font-mono text-2xl text-text-primary mb-2">
              Quick links
            </h2>
            <p className="text-sm text-text-muted max-w-2xl mb-6">
              The whole system, one click away.
            </p>
            <div className="grid sm:grid-cols-2 gap-2">
              <Link
                to="/"
                className="bg-surface border border-border rounded-md p-3 hover:border-amber/50 transition-colors flex items-center justify-between group"
              >
                <div>
                  <div className="text-sm text-text-primary font-medium">
                    Dashboard
                  </div>
                  <div className="text-[11px] font-mono text-text-muted">
                    Five-panel operator console
                  </div>
                </div>
                <ArrowRight
                  size={14}
                  className="text-text-dim group-hover:text-amber"
                  aria-hidden="true"
                />
              </Link>

              <Link
                to="/builder"
                className="bg-surface border border-border rounded-md p-3 hover:border-amber/50 transition-colors flex items-center justify-between group"
              >
                <div>
                  <div className="text-sm text-text-primary font-medium">
                    Thesis Builder
                  </div>
                  <div className="text-[11px] font-mono text-text-muted">
                    Visual editor for graph configs
                  </div>
                </div>
                <ArrowRight
                  size={14}
                  className="text-text-dim group-hover:text-amber"
                  aria-hidden="true"
                />
              </Link>

              <a
                href={EXTERNAL_LINKS.tradingDeskRepo}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-surface border border-border rounded-md p-3 hover:border-amber/50 transition-colors flex items-center justify-between group"
              >
                <div className="flex items-center gap-2">
                  <GitFork
                    size={14}
                    className="text-text-muted"
                    aria-hidden="true"
                  />
                  <div>
                    <div className="text-sm text-text-primary font-medium">
                      Skidudeaa/tradingDesk
                    </div>
                    <div className="text-[11px] font-mono text-text-muted">
                      Engine + backend + frontend
                    </div>
                  </div>
                </div>
                <ArrowUpRight
                  size={14}
                  className="text-text-dim group-hover:text-amber"
                  aria-hidden="true"
                />
              </a>

              <a
                href={EXTERNAL_LINKS.dialecticRepo}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-surface border border-border rounded-md p-3 hover:border-amber/50 transition-colors flex items-center justify-between group"
              >
                <div className="flex items-center gap-2">
                  <GitFork
                    size={14}
                    className="text-text-muted"
                    aria-hidden="true"
                  />
                  <div>
                    <div className="text-sm text-text-primary font-medium">
                      Skidudeaa/dialectic
                    </div>
                    <div className="text-[11px] font-mono text-text-muted">
                      LLM-mediated discussion rooms
                    </div>
                  </div>
                </div>
                <ArrowUpRight
                  size={14}
                  className="text-text-dim group-hover:text-amber"
                  aria-hidden="true"
                />
              </a>

              <a
                href="/docs/USER-MANUAL.md"
                className="bg-surface border border-border rounded-md p-3 hover:border-amber/50 transition-colors flex items-center justify-between group sm:col-span-2"
              >
                <div className="flex items-center gap-2">
                  <BookOpen
                    size={14}
                    className="text-text-muted"
                    aria-hidden="true"
                  />
                  <div>
                    <div className="text-sm text-text-primary font-medium">
                      User manual
                    </div>
                    <div className="text-[11px] font-mono text-text-muted">
                      End-to-end walkthrough — login, chat, thesis viewer, TradingView
                    </div>
                  </div>
                </div>
                <ArrowRight
                  size={14}
                  className="text-text-dim group-hover:text-amber"
                  aria-hidden="true"
                />
              </a>
            </div>
          </section>

          <footer className="border-t border-border pt-6 pb-12 text-[11px] font-mono text-text-dim flex justify-between flex-wrap gap-2">
            <span>tradingDesk · two analysts, one truthful desk</span>
            <Link to="/" className="hover:text-amber">
              ← back to the dashboard
            </Link>
          </footer>
        </main>
      </div>
    </div>
  );
}
