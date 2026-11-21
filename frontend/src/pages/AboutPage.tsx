import '../App.css'
import NotebookShell, { type NotebookView } from '../components/NotebookShell'
import { useLanguage } from '../i18n'

type AboutPageProps = { email?: string; onLogout: () => void; onNavigate: (view: NotebookView) => void }

function AboutPage({ email, onLogout, onNavigate }: AboutPageProps) {
  const { t } = useLanguage()
  return (
    <NotebookShell activeView="about" email={email} onNavigate={onNavigate} onLogout={onLogout}>
      <main className="settings-page">
        <header className="notebook-page-header"><div><p className="eyebrow">Notebook</p><h1>{t('about.title')}</h1></div></header>
        <section className="notebook-page-content about-content">
          <section className="about-intro"><div className="about-mark">N</div><div><p className="eyebrow">MCP-RAG-Notebook</p><h2>{t('about.introTitle')}</h2><p className="muted">{t('about.introText')}</p></div></section>
          <div className="about-grid"><section className="settings-card"><p className="eyebrow">{t('about.capabilities')}</p><h2>{t('about.features')}</h2><ul className="about-list"><li>{t('about.featureNotes')}</li><li>{t('about.featureDocuments')}</li><li>{t('about.featureChat')}</li><li>{t('about.featureMcp')}</li><li>{t('about.featureReview')}</li></ul></section><section className="settings-card"><p className="eyebrow">{t('about.technology')}</p><h2>{t('about.stack')}</h2><div className="tech-list"><span>React + TypeScript</span><span>FastAPI</span><span>PostgreSQL</span><span>Milvus</span><span>MinIO</span><span>Redis + Celery</span><span>DeepSeek</span><span>Model Context Protocol</span></div></section></div>
          <p className="about-version">{t('about.version')}</p>
        </section>
      </main>
    </NotebookShell>
  )
}

export default AboutPage
