import styles from './Header.module.css'

export default function Header() {
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <div className={styles.logoRow}>
          <img
            src="/logo.png"
            alt="CouncilAI logo"
            className={styles.logoImg}
          />
          <div>
            <h1 className={styles.title}>CouncilAI</h1>
            <p className={styles.subtitle}>IBM TechXchange 2026 · Multi-Agent Code Review</p>
          </div>
        </div>
        <div className={styles.badge}>
          <span className={styles.dot} />
          Live
        </div>
      </div>
    </header>
  )
}
