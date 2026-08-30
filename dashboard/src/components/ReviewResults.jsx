import { useState } from 'react'
import styles from './ReviewResults.module.css'

const AGENT_META = {
  security:     { icon: '🔒', label: 'Security',     color: 'red' },
  architecture: { icon: '🏗️', label: 'Architecture', color: 'purple' },
  testing:      { icon: '🧪', label: 'Testing',       color: 'cyan' },
  performance:  { icon: '⚡', label: 'Performance',   color: 'amber' },
}

/**
 * Parse the raw rationale string from judge.py into structured sections.
 *
 * The rationale format produced by judge.py:
 *   Line 0 : "REJECT: N supported finding(s)…" | "APPROVE: no supported…"
 *   Lines   :   "  • [role] finding text"        (reject triggers)
 *   Line    : "Unsupported finding(s)…:"
 *   Lines   :   "  – [role] finding text"         (unsupported)
 *   Line    : "Conflict note (N disagreement(s)…):"
 *   Lines   :   "  ↔ conflict string"             (conflict items)
 *   OR      : "No inter-agent conflicts detected."
 */
function parseRationale(rationale) {
  if (!rationale) return null

  const lines = rationale.split('\n')
  const result = {
    headline: '',
    isReject: false,
    rejectTriggers: [],   // { role, finding }
    unsupported: [],      // { role, finding }
    conflictNote: '',
    conflicts: [],        // raw conflict strings from judge
  }

  let section = 'header'

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue

    if (line.startsWith('REJECT:') || line.startsWith('APPROVE:')) {
      result.headline = line
      result.isReject = line.startsWith('REJECT:')
      section = 'triggers'
    } else if (line.startsWith('Unsupported finding')) {
      section = 'unsupported'
    } else if (line.startsWith('Conflict note')) {
      result.conflictNote = line
      section = 'conflicts'
    } else if (line === 'No inter-agent conflicts detected.') {
      result.conflictNote = line
      section = 'done'
    } else if (line.startsWith('•') && section === 'triggers') {
      const parsed = parseRoleAndFinding(line.replace(/^•\s*/, ''))
      if (parsed) result.rejectTriggers.push(parsed)
    } else if (line.startsWith('–') && section === 'unsupported') {
      const parsed = parseRoleAndFinding(line.replace(/^–\s*/, ''))
      if (parsed) result.unsupported.push(parsed)
    } else if (line.startsWith('↔') && section === 'conflicts') {
      result.conflicts.push(line.replace(/^↔\s*/, ''))
    }
  }

  return result
}

/** Extract { role, finding } from "[security] hardcoded credential found" */
function parseRoleAndFinding(text) {
  const match = text.match(/^\[(\w+)\]\s*(.+)/)
  if (!match) return { role: null, finding: text }
  return { role: match[1].toLowerCase(), finding: match[2] }
}

/**
 * Highlight code-like tokens in a finding string.
 * Wraps `backtick`, SELECT *, line references, and quoted tokens in <code> badges.
 */
function HighlightedFinding({ text }) {
  // Split on patterns: `code`, SELECT *, line N, "quoted"
  const parts = []
  const pattern = /(`[^`]+`|SELECT \*|line\s+\d+|"[^"]{1,40}")/gi
  let last = 0
  let match

  const regex = new RegExp(pattern.source, pattern.flags)
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) parts.push({ type: 'text', val: text.slice(last, match.index) })
    parts.push({ type: 'code', val: match[0].replace(/`/g, '') })
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push({ type: 'text', val: text.slice(last) })

  return (
    <span>
      {parts.map((p, i) =>
        p.type === 'code'
          ? <code key={i} className={styles.codeBadge}>{p.val}</code>
          : <span key={i}>{p.val}</span>
      )}
    </span>
  )
}

/** Parse conflict strings: "security passed but performance failed — agents disagree…" */
function parseConflictPair(conflict) {
  const m = conflict.match(/^(\w+)\s+passed\s+but\s+(\w+)\s+failed/i)
  if (!m) return null
  return { passer: m[1].toLowerCase(), failer: m[2].toLowerCase() }
}

export default function ReviewResults({ data, error, loading, prLabel }) {
  if (loading) return <LoadingState />
  if (error)   return <ErrorState message={error} />
  if (!data)   return <EmptyState />

  const agents    = data.details?.agents    ?? {}
  const conflicts = data.details?.conflicts
  const evidence  = data.details?.evidence
  const rationale = data.details?.rationale

  const passCount = Object.values(agents).filter(a => a.passed).length
  const failCount = Object.values(agents).filter(a => !a.passed).length

  const hasConflicts = conflicts?.has_conflicts ?? false

  return (
    <div className={styles.wrapper}>
      {/* Verdict banner */}
      <VerdictBanner verdict={data.verdict} summary={data.summary} prLabel={prLabel} requestId={data.request_id} hasConflicts={hasConflicts} />

      {/* Agent results grid */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitle}>Agent Results</div>
          <div className={styles.agentStat}>
            <span className={styles.statPass}>{passCount} passed</span>
            <span className={styles.statSep}>·</span>
            <span className={styles.statFail}>{failCount} failed</span>
          </div>
        </div>
        <div className={styles.agentsGrid}>
          {Object.entries(agents).map(([key, a]) => (
            <AgentCard key={key} agentKey={key} data={a} />
          ))}
        </div>
      </div>

      {/* Judge rationale */}
      {rationale && <JudgeRationale rationale={rationale} agents={agents} />}

      {/* Conflicts */}
      {conflicts && (
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div className={styles.cardTitle}>Conflict Detector</div>
            <span className={`${styles.countBadge} ${conflicts.has_conflicts ? styles.warnBadge : styles.okBadge}`}>
              {conflicts.has_conflicts ? 'Conflicts' : 'Clean'}
            </span>
          </div>
          {conflicts.has_conflicts
            ? conflicts.conflicts.map((c, i) => (
                <div key={i} className={styles.conflictItem}>
                  <span className={styles.conflictDot} />
                  {c}
                </div>
              ))
            : <p className={styles.dimNote}>No agent disagreements found.</p>
          }
        </div>
      )}

      {/* Evidence */}
      {evidence && (
        <div className={styles.card}>
          <div className={styles.cardTitle}>Evidence Checker</div>
          {evidence.supported_findings?.length > 0 && (
            <div className={styles.evidenceSection}>
              <div className={styles.evidenceLabel} style={{ color: 'var(--green)' }}>
                Supported ({evidence.supported_findings.length})
              </div>
              {evidence.supported_findings.map((f, i) => (
                <div key={i} className={`${styles.evidenceItem} ${styles.supported}`}>{f}</div>
              ))}
            </div>
          )}
          {evidence.unsupported_findings?.length > 0 && (
            <div className={styles.evidenceSection}>
              <div className={styles.evidenceLabel} style={{ color: 'var(--text-muted)' }}>
                Unsupported ({evidence.unsupported_findings.length})
              </div>
              {evidence.unsupported_findings.map((f, i) => (
                <div key={i} className={`${styles.evidenceItem} ${styles.unsupported}`}>{f}</div>
              ))}
            </div>
          )}
          {!evidence.supported_findings?.length && !evidence.unsupported_findings?.length && (
            <p className={styles.dimNote}>No findings to report.</p>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Judge Rationale ── */
function JudgeRationale({ rationale, agents }) {
  const parsed = parseRationale(rationale)
  if (!parsed) return null

  const isReject = parsed.isReject

  return (
    <div className={`${styles.card} ${styles.rationaleCard}`}>
      {/* Header row */}
      <div className={styles.rationaleHeader}>
        <span className={styles.cardTitle}>Judge Rationale</span>
        <span className={`${styles.rationaleBadge} ${isReject ? styles.rationaleReject : styles.rationaleApprove}`}>
          {isReject ? '✕ REJECT' : '✓ APPROVE'}
        </span>
      </div>

      {/* Decision summary */}
      <div className={`${styles.rationaleDecision} ${isReject ? styles.rationaleDecisionReject : styles.rationaleDecisionApprove}`}>
        <span
          className={styles.rationaleDecisionIcon}
          style={{ color: isReject ? 'var(--red)' : 'var(--green)' }}
        >{isReject ? '✕' : '✓'}</span>
        <span className={styles.rationaleDecisionText}>{parsed.headline}</span>
      </div>

      {/* Reject triggers — highlighted finding cards */}
      {parsed.rejectTriggers.length > 0 && (
        <div className={styles.rationaleSection}>
          <div className={styles.rationaleSectionLabel}>Triggered by</div>
          {parsed.rejectTriggers.map((item, i) => {
            const meta = AGENT_META[item.role] ?? { icon: '◉', label: item.role ?? 'Agent' }
            return (
              <div key={i} className={styles.rationaleFindingCard}>
                <div className={styles.rationaleFindingAgent}>
                  <span className={styles.rationaleFindingIcon}>{meta.icon}</span>
                  <span className={styles.rationaleFindingLabel}>{meta.label}</span>
                  <span className={styles.rationaleFindingBadge}>supported</span>
                </div>
                <div className={styles.rationaleFindingText}>
                  <HighlightedFinding text={item.finding} />
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Unsupported findings — compact dimmed list */}
      {parsed.unsupported.length > 0 && (
        <div className={styles.rationaleSection}>
          <div className={styles.rationaleSectionLabel}>Discarded (unsupported)</div>
          {parsed.unsupported.map((item, i) => {
            const meta = AGENT_META[item.role] ?? { icon: '◉', label: item.role ?? 'Agent' }
            return (
              <div key={i} className={styles.rationaleUnsupported}>
                <span className={styles.rationaleUnsupportedAgent}>{meta.icon} {meta.label}</span>
                <span className={styles.rationaleUnsupportedText}>
                  <HighlightedFinding text={item.finding} />
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Conflict chips — visual disagreement rows */}
      {parsed.conflicts.length > 0 && (
        <div className={styles.rationaleSection}>
          <div className={styles.rationaleSectionLabel}>Agent Disagreements</div>
          <div className={styles.rationaleConflictRows}>
            {parsed.conflicts.map((c, i) => {
              const pair = parseConflictPair(c)
              if (!pair) return <div key={i} className={styles.rationaleConflictRaw}>{c}</div>
              const pm = AGENT_META[pair.passer] ?? { icon: '◉', label: pair.passer }
              const fm = AGENT_META[pair.failer] ?? { icon: '◉', label: pair.failer }
              return (
                <div key={i} className={styles.rationaleConflictRow}>
                  <span className={styles.conflictChipPass}>
                    <span className={styles.conflictChipIcon}>✓</span>
                    {pm.icon} {pm.label} passed
                  </span>
                  <span className={styles.conflictVs}>vs</span>
                  <span className={styles.conflictChipFail}>
                    <span className={styles.conflictChipIcon}>✕</span>
                    {fm.icon} {fm.label} failed
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* No conflicts note */}
      {!parsed.conflicts.length && parsed.conflictNote && (
        <div className={styles.rationaleNoConflict}>
          <span className={styles.rationaleNoConflictDot} />
          {parsed.conflictNote}
        </div>
      )}
    </div>
  )
}


/* ── Verdict Banner ── */
function VerdictBanner({ verdict, summary, prLabel, requestId, hasConflicts }) {
  const isApprove  = verdict === 'APPROVE'
  const isReject   = verdict === 'REJECT'
  const escalate   = isReject && hasConflicts
  const color      = isApprove ? 'var(--green)' : escalate ? 'var(--amber)' : isReject ? 'var(--red)' : 'var(--amber)'
  const dimColor   = isApprove ? 'var(--green-dim)' : escalate ? 'var(--amber-dim)' : isReject ? 'var(--red-dim)' : 'var(--amber-dim)'

  return (
    <div className={styles.verdictBanner} style={{ borderColor: color + '40', background: dimColor }}>
      <div className={styles.verdictTop}>
        <div className={styles.verdictBadgeGroup}>
          <span className={styles.verdictBadge} style={{ color, borderColor: color + '55', background: color + '20' }}>
            {verdict === 'APPROVE' ? '✓ APPROVE' : verdict === 'REJECT' ? '✗ REJECT' : verdict}
          </span>
          {escalate && (
            <span className={styles.escalateBadge}>⚠ HUMAN REVIEW REQUIRED</span>
          )}
        </div>
        <div className={styles.verdictMeta}>
          {prLabel && <span>{prLabel}</span>}
          {requestId && <span className={styles.reqId}>#{requestId.slice(0, 8)}</span>}
        </div>
      </div>
      {summary && <p className={styles.verdictSummary}>{summary}</p>}
    </div>
  )
}

/* ── Agent Card ── */
function AgentCard({ agentKey, data }) {
  const [expanded, setExpanded] = useState(false)
  const meta = AGENT_META[agentKey] ?? { icon: '◉', label: agentKey, color: 'neutral' }
  const hasFindings = data.findings?.length > 0

  return (
    <div className={`${styles.agentCard} ${data.passed ? styles.pass : styles.fail}`}>
      <div className={styles.agentHeader}>
        <span className={styles.agentIcon}>{meta.icon}</span>
        <span className={styles.agentLabel}>{meta.label}</span>
        <span className={`${styles.agentStatus} ${data.passed ? styles.passText : styles.failText}`}>
          {data.passed ? 'PASS' : 'FAIL'}
        </span>
      </div>
      {hasFindings && (
        <>
          <button
            className={styles.toggleBtn}
            onClick={() => setExpanded(e => !e)}
          >
            {expanded ? '▾' : '▸'} {data.findings.length} finding{data.findings.length !== 1 ? 's' : ''}
          </button>
          {expanded && (
            <ul className={styles.findingsList}>
              {data.findings.map((f, i) => (
                <li key={i} className={styles.findingItem}>{f}</li>
              ))}
            </ul>
          )}
        </>
      )}
      {!hasFindings && data.passed && (
        <p className={styles.cleanNote}>No issues found.</p>
      )}
    </div>
  )
}

/* ── States ── */
function LoadingState() {
  return (
    <div className={styles.stateCenter}>
      <svg className={styles.loadingRing} viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="20" stroke="var(--border)" strokeWidth="3"/>
        <circle cx="24" cy="24" r="20" stroke="var(--accent)" strokeWidth="3"
          strokeDasharray="80" strokeDashoffset="60" strokeLinecap="round"/>
      </svg>
      <div className={styles.loadingTitle}>Pipeline running…</div>
      <div className={styles.loadingNote}>Security · Architecture · Testing · Performance</div>
    </div>
  )
}

function ErrorState({ message }) {
  return (
    <div className={`${styles.stateCenter} ${styles.errorBox}`}>
      <div className={styles.errorIcon}>⚠</div>
      <div className={styles.errorTitle}>Review failed</div>
      <div className={styles.errorMsg}>{message}</div>
      <div className={styles.errorHint}>Make sure the backend is running: <code>uvicorn main:app --reload</code> (from <code>backend/</code>)</div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className={styles.stateCenter}>
      <div className={styles.emptyIcon}>
        <svg viewBox="0 0 48 48" fill="none" width="48" height="48">
          <circle cx="24" cy="24" r="20" stroke="var(--border-light)" strokeWidth="1.5"/>
          <circle cx="24" cy="24" r="10" stroke="var(--border-light)" strokeWidth="1.5" strokeDasharray="3 2"/>
          <circle cx="24" cy="24" r="2.5" fill="var(--border-light)"/>
        </svg>
      </div>
      <div className={styles.emptyTitle}>No review yet</div>
      <div className={styles.emptyNote}>Select a demo PR on the left to trigger the multi-agent review pipeline.</div>
    </div>
  )
}
