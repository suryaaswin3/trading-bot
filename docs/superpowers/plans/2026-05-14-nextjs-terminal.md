# Next.js Trading Terminal — Streamlit Replacement

> **For agentic workers:** Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace Streamlit dashboard with professional Next.js trading terminal.

**Architecture:** Next.js App Router + Zustand + custom polling. Consumes existing FastAPI ops API. No backend changes.

**Tech Stack:** Next.js 14, TypeScript, TailwindCSS, Zustand, Recharts, lucide-react

---

### Task 1: Scaffold Next.js project

**Files:**
- Create: `trading-term/package.json`
- Create: `trading-term/tsconfig.json`
- Create: `trading-term/next.config.js`
- Create: `trading-term/tailwind.config.ts`
- Create: `trading-term/postcss.config.js`
- Create: `trading-term/.env.local`

- [ ] **Create package.json**
- [ ] **Create tsconfig.json**
- [ ] **Create next.config.js**
- [ ] **Create tailwind.config.ts**
- [ ] **Create postcss.config.js**
- [ ] **Create .env.local**
- [ ] **Install deps**

### Task 2: Core layer — API client + store + poller

**Files:**
- Create: `trading-term/src/lib/api.ts`
- Create: `trading-term/src/lib/store.ts`
- Create: `trading-term/src/lib/usePolling.ts`

### Task 3: App shell — layout, globals, providers

**Files:**
- Create: `trading-term/src/app/globals.css`
- Create: `trading-term/src/app/layout.tsx`
- Create: `trading-term/src/app/page.tsx`

### Task 4: UI components — topbar, controls, feed, risk, charts, bottom

**Files:**
- Create: `trading-term/src/components/TopBar.tsx`
- Create: `trading-term/src/components/ControlsPanel.tsx`
- Create: `trading-term/src/components/ExecutionFeed.tsx`
- Create: `trading-term/src/components/RiskPanel.tsx`
- Create: `trading-term/src/components/BottomPanel.tsx`
- Create: `trading-term/src/components/Charts.tsx`
- Create: `trading-term/src/components/ui/button.tsx`
- Create: `trading-term/src/components/ui/badge.tsx`
- Create: `trading-term/src/components/ui/card.tsx`
- Create: `trading-term/src/components/ui/tabs.tsx`
- Create: `trading-term/src/lib/utils.ts`

### Task 5: Verify build

- [ ] `npm run build`
- [ ] Fix TS errors
- [ ] Verify output
