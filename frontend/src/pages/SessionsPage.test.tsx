import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listConversations } from '../api/conversations'
import { LanguageProvider } from '../i18n-provider'
import SessionsPage from './SessionsPage'

vi.mock('../api/conversations', () => ({
  deleteConversation: vi.fn(),
  listConversations: vi.fn(),
  updateConversation: vi.fn(),
}))

const makeSession = (id: string, title: string) => ({
  id,
  knowledge_base_id: 'knowledge-base-1',
  title,
  model_name: 'deepseek-chat',
  created_at: '2026-10-20T10:00:00Z',
  updated_at: '2026-10-20T10:00:00Z',
  message_count: 2,
  archived_at: null,
})

describe('SessionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not let an older search response replace newer results', async () => {
    let resolveInitial: (value: {
      items: ReturnType<typeof makeSession>[]
      count: number
    }) => void = () => undefined
    const initialResult = new Promise<{
      items: ReturnType<typeof makeSession>[]
      count: number
    }>((resolve) => {
      resolveInitial = resolve
    })

    vi.mocked(listConversations).mockImplementation(({ query } = {}) => (
      query
        ? Promise.resolve({
            items: [makeSession('newer', '新搜索结果')],
            count: 1,
          })
        : initialResult
    ))

    render(
      <LanguageProvider>
        <SessionsPage onNavigate={() => undefined} />
      </LanguageProvider>,
    )

    await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(1))
    fireEvent.change(screen.getByRole('textbox', { name: '搜索会话标题' }), {
      target: { value: '新搜索' },
    })

    await screen.findByRole('button', { name: /新搜索结果/ })
    await act(async () => {
      resolveInitial({
        items: [makeSession('older', '旧搜索结果')],
        count: 1,
      })
    })

    expect(screen.getByRole('button', { name: /新搜索结果/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /旧搜索结果/ })).not.toBeInTheDocument()
  })

  it('reloads sessions when the refresh action is used', async () => {
    vi.mocked(listConversations)
      .mockResolvedValueOnce({
        items: [makeSession('initial', '当前会话')],
        count: 1,
      })
      .mockResolvedValueOnce({
        items: [makeSession('refreshed', '刚更新的会话')],
        count: 1,
      })

    render(
      <LanguageProvider>
        <SessionsPage onNavigate={() => undefined} />
      </LanguageProvider>,
    )

    await screen.findByRole('button', { name: /当前会话/ })
    fireEvent.click(screen.getByRole('button', { name: '刷新' }))

    await screen.findByRole('button', { name: /刚更新的会话/ })
    expect(listConversations).toHaveBeenCalledTimes(2)
  })
})
