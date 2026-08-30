import { useState, useCallback } from 'react'
import Header from './components/Header.jsx'
import DemoButtons from './components/DemoButtons.jsx'
import PipelineDiagram from './components/PipelineDiagram.jsx'
import ReviewResults from './components/ReviewResults.jsx'
import { postReview } from './api.js'
import { DEMO_DIFFS } from './data/demoDiffs.js'
import styles from './App.module.css'

export default function App() {
  // triggering: null | PR number currently being fetched
  const [triggering, setTriggering] = useState(null)
  // results: { [prN]: { data, error } }
  const [results, setResults] = useState({})
  // selectedPr: number | null
  const [selectedPr, setSelectedPr] = useState(null)

  const trigger = useCallback(async (prN) => {
    const pr = DEMO_DIFFS[prN]
    if (!pr) return

    setTriggering(prN)
    setSelectedPr(prN)
    // Clear previous result for this PR so we show loading
    setResults(prev => ({ ...prev, [prN]: { data: null, error: null } }))

    try {
      const data = await postReview(pr.diff, pr.context)
      setResults(prev => ({ ...prev, [prN]: { data, error: null } }))
    } catch (err) {
      setResults(prev => ({ ...prev, [prN]: { data: null, error: err.message } }))
    } finally {
      setTriggering(null)
    }
  }, [])

  const current = selectedPr != null ? results[selectedPr] : null
  const isLoading = triggering !== null && triggering === selectedPr

  return (
    <div className={styles.appShell}>
      <Header />

      <main className={styles.main}>
        <div className={styles.content}>

          {/* Left column: pipeline + controls */}
          <aside className={styles.sidebar}>
            <DemoButtons
              triggering={triggering}
              onTrigger={trigger}
              selectedPr={selectedPr}
            />
            <PipelineDiagram
              reviewData={current?.data ?? null}
              loading={isLoading}
            />
          </aside>

          {/* Right column: results */}
          <section className={styles.results}>
            <ReviewResults
              data={current?.data ?? null}
              error={current?.error ?? null}
              loading={isLoading}
              prLabel={selectedPr != null ? DEMO_DIFFS[selectedPr]?.label : null}
              prEscalate={selectedPr != null ? DEMO_DIFFS[selectedPr]?.escalate : false}
            />
          </section>

        </div>
      </main>

      <footer className={styles.footer}>
        CouncilAI · IBM TechXchange Hackathon 2026 · Multi-Agent Code Review
      </footer>
    </div>
  )
}
