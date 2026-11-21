import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import App from './App'
import { LanguageProvider } from './i18n-provider'
import SettingsPage from './pages/SettingsPage'


describe('App', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders without crashing', () => {
    const { container } = render(<App />)

    expect(container).not.toBeEmptyDOMElement()
  })

  it('switches the interface language and persists the choice', () => {
    const view = render(
      <LanguageProvider>
        <SettingsPage
          email="test@example.com"
          onLogout={() => undefined}
          onNavigate={() => undefined}
        />
      </LanguageProvider>,
    )

    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: 'en-US' },
    })

    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Notes' })).toBeInTheDocument()
    expect(localStorage.getItem('notebook_language')).toBe('en-US')

    view.unmount()
    render(
      <LanguageProvider>
        <SettingsPage
          email="test@example.com"
          onLogout={() => undefined}
          onNavigate={() => undefined}
        />
      </LanguageProvider>,
    )

    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
  })
})
