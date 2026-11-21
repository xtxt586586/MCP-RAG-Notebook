import WorkspacePage from './pages/WorkspacePage'
import { LanguageProvider } from './i18n-provider'

export default function App() {
  return (
    <LanguageProvider>
      <WorkspacePage />
    </LanguageProvider>
  )
}
