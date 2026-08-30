import styles from './DemoButtons.module.css'
import { DEMO_DIFFS } from '../data/demoDiffs.js'

const EXPECTED_COLORS = {
  APPROVE: 'green',
  REJECT: 'red',
  PENDING: 'amber',
}

export default function DemoButtons({ triggering, onTrigger }) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionIcon}>▶</span>
        <span className={styles.sectionTitle}>Demo Scenarios</span>
      </div>
      <div className={styles.row}>
        {Object.entries(DEMO_DIFFS).map(([n, pr]) => {
          const isRunning = triggering === Number(n)
          const colorClass = styles[EXPECTED_COLORS[pr.expectedVerdict] ?? 'neutral']
          const btnClass = pr.escalate ? styles.amber : colorClass
          return (
            <button
              key={n}
              className={`${styles.btn} ${btnClass} ${isRunning ? styles.running : ''}`}
              disabled={triggering !== null}
              onClick={() => onTrigger(Number(n))}
            >
              {isRunning ? (
                <span className={styles.btnInner}>
                  <Spinner />
                  <span className={styles.runText}>Running pipeline…</span>
                </span>
              ) : (
                <span className={styles.btnInner}>
                  <span className={styles.prNum}>PR #{n}</span>
                  <span className={styles.prTitle}>{pr.description}</span>
                  {pr.escalate
                    ? <span className={`${styles.tag} ${styles.escalate}`}>HUMAN REVIEW REQUIRED</span>
                    : <span className={`${styles.tag} ${colorClass}`}>{pr.expectedVerdict}</span>
                  }
                </span>
              )}
            </button>
          )
        })}
      </div>
    </section>
  )
}

function Spinner() {
  return (
    <svg className={styles.spinner} viewBox="0 0 20 20" fill="none">
      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="2" strokeDasharray="40" strokeDashoffset="10" strokeLinecap="round"/>
    </svg>
  )
}
