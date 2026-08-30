import { useState, useRef, useEffect } from 'react'
import styles from './DemoButtons.module.css'
import { DEMO_DIFFS } from '../data/demoDiffs.js'

const EXPECTED_COLORS = {
  APPROVE: 'green',
  REJECT: 'red',
  PENDING: 'amber',
}

const PRIMARY_PRS = [1, 2, 3]
const EXTRA_PRS = [4, 5, 6, 7]

export default function DemoButtons({ triggering, onTrigger, selectedPr }) {
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const selectedExtraPr = EXTRA_PRS.includes(selectedPr) ? DEMO_DIFFS[selectedPr] : null

  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionIcon}>▶</span>
        <span className={styles.sectionTitle}>Demo Scenarios</span>
      </div>

      {/* Primary Scenarios: PR #1, PR #2, PR #3 */}
      <div className={styles.primaryRow}>
        {PRIMARY_PRS.map((n) => {
          const pr = DEMO_DIFFS[n]
          if (!pr) return null
          const isRunning = triggering === n
          const isSelected = selectedPr === n
          const colorClass = styles[EXPECTED_COLORS[pr.expectedVerdict] ?? 'neutral']
          const btnClass = pr.escalate ? styles.amber : colorClass

          return (
            <button
              key={n}
              className={`${styles.btn} ${btnClass} ${isRunning ? styles.running : ''} ${isSelected ? styles.selected : ''}`}
              disabled={triggering !== null}
              onClick={() => onTrigger(n)}
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
                  {pr.escalate ? (
                    <span className={`${styles.tag} ${styles.escalate}`}>HUMAN REVIEW REQUIRED</span>
                  ) : (
                    <span className={`${styles.tag} ${colorClass}`}>{pr.expectedVerdict}</span>
                  )}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* "More Scenarios" Dropdown for PR #4, PR #5, PR #6, PR #7 */}
      <div className={styles.dropdownContainer} ref={dropdownRef}>
        <button
          type="button"
          className={`${styles.dropdownToggle} ${dropdownOpen ? styles.dropdownToggleActive : ''} ${selectedExtraPr ? styles.hasActiveScenario : ''}`}
          onClick={() => setDropdownOpen((prev) => !prev)}
        >
          <span className={styles.dropdownToggleLeft}>
            <span className={styles.dropdownLabel}>More Scenarios</span>
            {selectedExtraPr && (
              <span className={styles.activeScenarioBadge}>
                PR #{selectedPr} — {selectedExtraPr.description}
              </span>
            )}
          </span>
          <span className={styles.chevron}>{dropdownOpen ? '▲' : '▼'}</span>
        </button>

        {dropdownOpen && (
          <div className={styles.dropdownMenu}>
            {EXTRA_PRS.map((n) => {
              const pr = DEMO_DIFFS[n]
              if (!pr) return null
              const isRunning = triggering === n
              const isSelected = selectedPr === n
              const colorClass = styles[EXPECTED_COLORS[pr.expectedVerdict] ?? 'neutral']

              return (
                <button
                  key={n}
                  className={`${styles.dropdownItem} ${colorClass} ${isRunning ? styles.running : ''} ${isSelected ? styles.selectedItem : ''}`}
                  disabled={triggering !== null}
                  onClick={() => {
                    onTrigger(n)
                    setDropdownOpen(false)
                  }}
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
                      {pr.agentTag && (
                        <span className={styles.agentTag}>{pr.agentTag}</span>
                      )}
                      <span className={`${styles.tag} ${colorClass}`}>{pr.expectedVerdict}</span>
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}
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
