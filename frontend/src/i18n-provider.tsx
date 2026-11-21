import { useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  getInitialLanguage,
  LanguageContext,
  messages,
  type Language,
} from './i18n'

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(getInitialLanguage)

  useEffect(() => {
    localStorage.setItem('notebook_language', language)
    document.documentElement.lang = language
  }, [language])

  const value = useMemo(() => ({
    language,
    setLanguage,
    t: (key: string) => messages[language][key] ?? messages['zh-CN'][key] ?? key,
  }), [language])

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}
