import styles from './PipelineDiagram.module.css'

const AGENTS = [
  { key: 'security',     label: 'Security',     icon: '🔒', color: 'red' },
  { key: 'architecture', label: 'Architecture', icon: '🏗️', color: 'purple' },
  { key: 'testing',      label: 'Testing',      icon: '🧪', color: 'cyan' },
  { key: 'performance',  label: 'Performance',  icon: '⚡', color: 'amber' },
]

function statusClass(agentData, loading) {
  if (loading) return 'loading'
  if (!agentData) return 'idle'
  return agentData.passed ? 'pass' : 'fail'
}

export default function PipelineDiagram({ reviewData, loading }) {
  const agents = reviewData?.details?.agents ?? {}
  const hasConflicts = reviewData?.details?.conflicts?.has_conflicts
  const verdict = reviewData?.verdict

  return (
    <div className={styles.wrapper}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionIcon}>⚙</span>
        <span className={styles.sectionTitle}>Pipeline</span>
      </div>

      {/* Stage 1 — Parallel agents */}
      <div className={styles.stage}>
        <div className={styles.stageLabel}>Parallel Agents</div>
        <div className={styles.agentRow}>
          {AGENTS.map((a) => {
            const data = agents[a.key]
            const sc = statusClass(data, loading)
            return (
              <div key={a.key} className={`${styles.agentCard} ${styles[a.color]} ${styles[sc]}`}>
                <span className={styles.agentIcon}>{a.icon}</span>
                <span className={styles.agentName}>{a.label}</span>
                <StatusPip status={sc} />
              </div>
            )
          })}
        </div>
      </div>

      {/* Arrow */}
      <Arrow active={!!reviewData || loading} />

      {/* Stage 2 — Conflict Detector */}
      <div className={styles.stage}>
        <div className={styles.stageLabel}>Conflict Detector</div>
        <div className={`${styles.pipeCard} ${loading ? styles.loading : reviewData ? (hasConflicts ? styles.warn : styles.ok) : styles.idle}`}>
          <span className={styles.pipeIcon}>⚡</span>
          <span className={styles.pipeName}>Conflict Detector</span>
          {reviewData && !loading && (
            <span className={`${styles.pipeStatus} ${hasConflicts ? styles.warnText : styles.okText}`}>
              {hasConflicts ? 'Conflicts' : 'Clean'}
            </span>
          )}
        </div>
      </div>

      {/* Arrow */}
      <Arrow active={!!reviewData || loading} />

      {/* Stage 3 — Evidence Checker */}
      <div className={styles.stage}>
        <div className={styles.stageLabel}>Evidence Checker</div>
        <div className={`${styles.pipeCard} ${loading ? styles.loading : reviewData ? styles.ok : styles.idle}`}>
          <span className={styles.pipeIcon}>🔍</span>
          <span className={styles.pipeName}>Evidence Checker</span>
          {reviewData && !loading && (
            <EvidenceSummary evidence={reviewData.details?.evidence} />
          )}
        </div>
      </div>

      {/* Arrow */}
      <Arrow active={!!reviewData || loading} />

      {/* Stage 4 — Final Judge */}
      <div className={styles.stage}>
        <div className={styles.stageLabel}>Final Judge</div>
        <div className={`${styles.pipeCard} ${styles.judgeCard} ${loading ? styles.loading : verdict ? styles[`verdict${verdict}`] : styles.idle}`}>
          <span className={styles.pipeIcon}>⚖️</span>
          <span className={styles.pipeName}>Final Judge</span>
          {verdict && !loading && (
            <VerdictBadge verdict={verdict} />
          )}
        </div>
      </div>
    </div>
  )
}

function Arrow({ active }) {
  return (
    <div className={`${styles.arrow} ${active ? styles.arrowActive : ''}`}>
      <svg width="2" height="20" viewBox="0 0 2 20" fill="none">
        <line x1="1" y1="0" x2="1" y2="14" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2"/>
        <path d="M1 20 L-2 13 L4 13 Z" fill="currentColor"/>
      </svg>
    </div>
  )
}

function StatusPip({ status }) {
  const map = {
    idle: styles.pipIdle,
    loading: styles.pipLoading,
    pass: styles.pipPass,
    fail: styles.pipFail,
  }
  return <span className={`${styles.pip} ${map[status] ?? ''}`} />
}

function EvidenceSummary({ evidence }) {
  if (!evidence) return null
  const s = evidence.supported_findings?.length ?? 0
  const u = evidence.unsupported_findings?.length ?? 0
  return (
    <span className={styles.pipeStatus} style={{ color: 'var(--text-dim)' }}>
      {s}S · {u}U
    </span>
  )
}

function VerdictBadge({ verdict }) {
  const color = verdict === 'APPROVE' ? 'var(--green)' : verdict === 'REJECT' ? 'var(--red)' : 'var(--amber)'
  return (
    <span className={styles.verdictBadge} style={{ color, borderColor: color + '44', background: color + '18' }}>
      {verdict}
    </span>
  )
}
