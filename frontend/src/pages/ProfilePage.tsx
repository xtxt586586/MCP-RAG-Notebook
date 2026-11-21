import { useState } from 'react'

import '../App.css'

import { apiRequest } from '../api/client'
import NotebookShell, { type NotebookView } from '../components/NotebookShell'
import type { User } from '../types'
import { useLanguage } from '../i18n'

type ProfilePageProps = {
  user: User
  email?: string
  onUserChange: (user: User) => void
  onLogout: () => void
  onNavigate: (view: NotebookView) => void
}

function ProfilePage({ user, email, onUserChange, onLogout, onNavigate }: ProfilePageProps) {
  const { t } = useLanguage()
  const [form, setForm] = useState({
    display_name: user.display_name ?? '',
    phone: user.phone ?? '',
    gender: user.gender ?? '',
    bio: user.bio ?? '',
  })
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  function updateField(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  async function saveProfile() {
    setBusy(true)
    setMessage('')
    setError('')
    try {
      const updated = await apiRequest<User>('/api/v1/profile', {
        method: 'PUT',
        body: JSON.stringify(form),
      })
      onUserChange(updated)
      setMessage(t('profile.saved'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('profile.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  async function changePassword() {
    if (!oldPassword || !newPassword || !confirmPassword) {
      setError(t('profile.fillPassword'))
      return
    }
    setBusy(true)
    setMessage('')
    setError('')
    try {
      await apiRequest<User>('/api/v1/profile/password', {
        method: 'POST',
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
      })
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setMessage(t('profile.passwordSaved'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('profile.passwordFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <NotebookShell activeView="profile" email={email} onNavigate={onNavigate} onLogout={onLogout}>
      <main className="settings-page">
        <header className="notebook-page-header">
          <div><p className="eyebrow">{t('profile.eyebrow')}</p><h1>{t('profile.title')}</h1></div>
        </header>
        <section className="notebook-page-content settings-content">
          {(message || error) && <p className={`message ${error ? 'error-message' : 'success-message'}`}>{error || message}</p>}
          <div className="settings-grid">
            <section className="settings-card">
              <div className="settings-card-heading"><div><p className="eyebrow">{t('profile.profile')}</p><h2>{t('profile.basic')}</h2></div><span className="profile-avatar">{(form.display_name || email || 'U').slice(0, 1).toUpperCase()}</span></div>
              <label className="field-label">{t('profile.email')}<input value={user.email} readOnly /></label>
              <label className="field-label">{t('profile.nickname')}<input value={form.display_name} onChange={(event) => updateField('display_name', event.target.value)} placeholder={t('profile.nicknamePlaceholder')} /></label>
              <div className="settings-form-row">
                <label className="field-label">{t('profile.phone')}<input value={form.phone} onChange={(event) => updateField('phone', event.target.value)} placeholder={t('profile.optional')} /></label>
                <label className="field-label">{t('profile.gender')}<select value={form.gender} onChange={(event) => updateField('gender', event.target.value)}><option value="">{t('profile.unset')}</option><option value="female">{t('profile.female')}</option><option value="male">{t('profile.male')}</option><option value="other">{t('profile.other')}</option></select></label>
              </div>
              <label className="field-label">{t('profile.bio')}<textarea className="profile-bio" value={form.bio} onChange={(event) => updateField('bio', event.target.value)} placeholder={t('profile.bioPlaceholder')} /></label>
              <div className="settings-actions"><button className="primary-button" type="button" onClick={() => void saveProfile()} disabled={busy}>{t('profile.save')}</button></div>
            </section>
            <section className="settings-card">
              <p className="eyebrow">{t('profile.security')}</p><h2>{t('profile.passwordTitle')}</h2>
              <p className="muted">{t('profile.passwordHint')}</p>
              <label className="field-label">{t('profile.currentPassword')}<input type="password" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} autoComplete="current-password" /></label>
              <label className="field-label">{t('profile.newPassword')}<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" /></label>
              <label className="field-label">{t('profile.confirmPassword')}<input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" /></label>
              <div className="settings-actions"><button className="secondary-button" type="button" onClick={() => void changePassword()} disabled={busy}>{t('profile.updatePassword')}</button></div>
            </section>
          </div>
        </section>
      </main>
    </NotebookShell>
  )
}

export default ProfilePage
