import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

const user = {
  id: 'user-e2e',
  email: 'e2e@example.com',
  display_name: '测试用户',
}

const knowledgeBase = {
  id: 'kb-e2e',
  name: '默认知识库',
  description: '',
  document_count: 0,
}

async function mockAuthenticatedBackend(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('rag_access_token', 'e2e-token')
  })

  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({ json: user }),
  )
  await page.route('**/api/v1/knowledge-bases', (route) =>
    route.fulfill({ json: [knowledgeBase] }),
  )
  await page.route('**/api/v1/knowledge-bases/current', (route) =>
    route.fulfill({ json: knowledgeBase }),
  )
  await page.route('**/api/v1/documents?*', (route) =>
    route.fulfill({
      json: {
        items: [],
        count: 0,
        knowledge_base_id: knowledgeBase.id,
      },
    }),
  )
  await page.route('**/api/v1/notes/templates', (route) =>
    route.fulfill({ json: [] }),
  )
}

test('authenticated user starts at welcome and can open notes', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: /欢迎回来/ })).toBeVisible()
  await page.getByRole('button', { name: '笔记', exact: true }).click()
  await expect(page.getByRole('heading', { name: '笔记', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '笔记', exact: true })).toHaveAttribute('aria-current', 'page')
})

test('welcome, notes, and note details have no WCAG 2.1 A/AA violations', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.route('**/api/v1/notes?*', (route) => route.fulfill({ json: [{
    id: 'note-a11y',
    user_id: user.id,
    knowledge_base_id: knowledgeBase.id,
    source_document_id: null,
    title: 'Accessibility test note',
    content: 'A short note for the accessibility scan.',
    metadata: { category: 'study', tags: [] },
    created_at: '2026-08-22T10:00:00Z',
    updated_at: '2026-08-22T10:00:00Z',
  }] }))
  await page.goto('/')

  const violationsByView: Array<{ view: string; violations: unknown }> = []
  const scan = async (view: string) => {
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    if (results.violations.length > 0) {
      violationsByView.push({
        view,
        violations: results.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: violation.nodes.map((node) => ({
            target: node.target,
            message: node.any[0]?.message,
          })),
        })),
      })
    }
  }

  await scan('welcome')
  await page.getByRole('button', { name: '笔记', exact: true }).click()
  await expect(page.getByRole('heading', { name: '笔记', exact: true })).toBeVisible()
  await scan('notes')
  await page.getByRole('button', { name: /Accessibility test note/ }).click()
  await expect(page.getByRole('dialog', { name: '笔记详情' })).toBeVisible()
  await scan('note detail')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'AI 对话', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'AI 对话' })).toBeVisible()
  await scan('chat')

  await page.getByRole('button', { name: '会话管理', exact: true }).click()
  await expect(page.getByRole('heading', { name: '会话管理' })).toBeVisible()
  await scan('sessions')

  await page.getByRole('button', { name: '每日回顾', exact: true }).click()
  await expect(page.getByRole('heading', { name: '每日回顾' })).toBeVisible()
  await scan('daily review')

  await page.getByRole('button', { name: '知识图谱', exact: true }).click()
  await expect(page.getByRole('heading', { name: '知识图谱' })).toBeVisible()
  await scan('knowledge graph')

  await page.getByRole('button', { name: '知识库', exact: true }).click()
  await expect(page.getByRole('heading', { name: '知识库管理', exact: true })).toBeVisible()
  await scan('knowledge workspace')

  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await scan('dark knowledge workspace')
  await page.getByRole('button', { name: '笔记', exact: true }).click()
  await scan('dark notes')

  expect(violationsByView, JSON.stringify(violationsByView, null, 2)).toEqual([])
})

test('a late note search cannot replace the newest results', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let releaseOldSearch: (() => void) | undefined
  let markOldSearchStarted: (() => void) | undefined
  const oldSearchStarted = new Promise<void>((resolve) => {
    markOldSearchStarted = resolve
  })

  const makeNote = (id: string, title: string) => ({
    id,
    user_id: user.id,
    knowledge_base_id: knowledgeBase.id,
    source_document_id: null,
    title,
    content: `${title} content`,
    metadata: { category: 'study', tags: [] },
    vector_index_status: 'ready',
    created_at: '2026-08-22T10:00:00Z',
    updated_at: '2026-08-22T10:00:00Z',
  })

  await page.route('**/api/v1/notes?*', async (route) => {
    const query = new URL(route.request().url()).searchParams.get('query')
    if (query === 'old') {
      markOldSearchStarted?.()
      await new Promise<void>((resolve) => {
        releaseOldSearch = resolve
      })
      return route.fulfill({ json: [makeNote('old-note', '旧搜索结果')] })
    }
    if (query === 'new') {
      return route.fulfill({ json: [makeNote('new-note', '新搜索结果')] })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto('/?view=notes')
  const search = page.getByRole('textbox', { name: '搜索笔记...' })
  await search.fill('old')
  await oldSearchStarted
  await search.fill('new')
  await expect(page.getByRole('heading', { name: '新搜索结果' })).toBeVisible()

  releaseOldSearch?.()
  await expect(page.getByRole('heading', { name: '新搜索结果' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '旧搜索结果' })).toHaveCount(0)
})

test('user can open a note editor without a blank page', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.route('**/api/v1/notes?*', (route) =>
    route.fulfill({
      json: [{
        id: 'note-e2e',
        user_id: user.id,
        knowledge_base_id: knowledgeBase.id,
        source_document_id: null,
        title: 'MCP 学习笔记',
        content: '# MCP\n\n这是编辑器测试内容。',
        metadata: { category: 'study', tags: ['MCP'] },
        created_at: '2026-08-22T10:00:00Z',
        updated_at: '2026-08-22T10:00:00Z',
      }],
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: '笔记', exact: true }).click()
  await page.getByRole('button', { name: /MCP 学习笔记/ }).click()
  await expect(page.getByRole('button', { name: '关闭' })).toBeFocused()
  const noteDialog = page.getByRole('dialog', { name: '笔记详情' })
  const noteFocusableElements = noteDialog.locator(
    'a[href]:visible, button:not([disabled]):visible, input:not([disabled]):visible, select:not([disabled]):visible, textarea:not([disabled]):visible, [tabindex]:not([tabindex="-1"]):visible',
  )
  await page.keyboard.press('Shift+Tab')
  await expect(noteFocusableElements.last()).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(noteFocusableElements.first()).toBeFocused()
  await page.getByTestId('edit-note-button').click()

  await expect(page.locator('input.standalone-note-title')).toHaveValue('MCP 学习笔记')
  await expect(page.getByRole('button', { name: '大纲' })).toBeVisible()
  await expect(page.locator('.rich-editor-toolbar')).toBeVisible()
  await expect(page.locator('.ProseMirror')).toContainText('这是编辑器测试内容。')

  await page.locator('input.standalone-note-title').fill('尚未保存的标题')
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('尚未保存的修改')
    await dialog.dismiss()
  })
  await page.getByRole('button', { name: '取消' }).first().click()
  await expect(page.locator('input.standalone-note-title')).toHaveValue('尚未保存的标题')

  page.once('dialog', (dialog) => dialog.accept())
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('笔记详情')).toHaveCount(0)
  await expect(page.locator('.note-card')).toBeFocused()
})

test('note editor accessibility labels follow the selected language', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.addInitScript(() => {
    window.localStorage.setItem('notebook_language', 'en-US')
  })
  await page.route('**/api/v1/notes?*', (route) =>
    route.fulfill({
      json: [{
        id: 'note-e2e',
        user_id: user.id,
        knowledge_base_id: knowledgeBase.id,
        source_document_id: null,
        title: 'MCP 学习笔记',
        content: '# MCP\n\n这是编辑器测试内容。',
        metadata: { category: 'study', tags: ['MCP'] },
        created_at: '2026-08-22T10:00:00Z',
        updated_at: '2026-08-22T10:00:00Z',
      }],
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'Notes', exact: true }).click()
  await page.getByRole('button', { name: /MCP 学习笔记/ }).click()
  const noteDialog = page.getByRole('dialog', { name: 'Note detail' })
  await expect(noteDialog).toBeVisible()
  await noteDialog.getByTestId('edit-note-button').click()

  await expect(page.locator('.rich-editor-toolbar')).toHaveAttribute('aria-label', 'Editor toolbar')
  await expect(page.getByRole('combobox', { name: 'Heading level' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Bold' })).toBeVisible()
})

test('note drafts are isolated to the signed-in account', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.addInitScript(() => {
    window.localStorage.setItem(
      'rag_notebook_note_draft:another@example.com',
      JSON.stringify({
        title: '其他账号的草稿',
        content: '不应出现在当前账号中',
        category: '',
        tags: '',
      }),
    )
  })
  await page.route('**/api/v1/notes?*', (route) => route.fulfill({ json: [] }))

  await page.goto('/')
  await page.getByRole('button', { name: '笔记', exact: true }).click()
  await page.locator('.notes-page header').getByRole('button', { name: '新建笔记' }).click()

  await expect(page.locator('input.note-title-input')).toHaveValue('')
  await expect(page.getByText('已恢复本地草稿')).toHaveCount(0)

  await page.locator('input.note-title-input').fill('当前账号的草稿')
  await expect.poll(() => page.evaluate(() =>
    window.localStorage.getItem('rag_notebook_note_draft:e2e@example.com'),
  )).toContain('当前账号的草稿')
  expect(await page.evaluate(() =>
    window.localStorage.getItem('rag_notebook_note_draft:another@example.com'),
  )).toContain('其他账号的草稿')
})

test('user can upload multiple knowledge-base documents in order', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  const uploadedFiles: string[] = []
  let releaseSecondUpload: (() => void) | undefined
  let markSecondUploadStarted: (() => void) | undefined
  const secondUploadStarted = new Promise<void>((resolve) => {
    markSecondUploadStarted = resolve
  })

  await page.route('**/api/v1/documents/upload', async (route) => {
    const requestBody = route.request().postDataBuffer()?.toString('latin1') ?? ''
    const fileName = requestBody.match(/name="file"; filename="([^"]+)"/)?.[1]
    if (!fileName) {
      return route.fulfill({ status: 400, json: { detail: 'Missing uploaded file' } })
    }

    uploadedFiles.push(fileName)
    if (fileName === 'second.txt') {
      markSecondUploadStarted?.()
      await new Promise<void>((resolve) => {
        releaseSecondUpload = resolve
      })
    }

    const id = fileName === 'first.txt' ? 'document-first' : 'document-second'
    return route.fulfill({
      json: {
        id,
        knowledge_base_id: knowledgeBase.id,
        file_name: fileName,
        size_bytes: 5,
        status: 'UPLOADED',
        duplicate: false,
      },
    })
  })
  await page.route('**/api/v1/documents/document-*', (route) =>
    route.fulfill({
      json: {
        id: route.request().url().endsWith('document-first') ? 'document-first' : 'document-second',
        knowledge_base_id: knowledgeBase.id,
        file_name: route.request().url().endsWith('document-first') ? 'first.txt' : 'second.txt',
        size_bytes: 5,
        status: 'READY',
      },
    }),
  )

  await page.goto('/?view=workspace')
  await page.getByRole('button', { name: '上传文档' }).click()
  await page.locator('#document-file-input').setInputFiles([
    { name: 'first.txt', mimeType: 'text/plain', buffer: Buffer.from('first') },
    { name: 'second.txt', mimeType: 'text/plain', buffer: Buffer.from('other') },
  ])

  await expect(page.getByText('first.txt · 5 B')).toBeVisible()
  await expect(page.getByText('second.txt · 5 B')).toBeVisible()
  await page.getByRole('button', { name: '上传并处理 (2)' }).click()
  await secondUploadStarted

  await expect(page.getByRole('status').filter({ hasText: '正在上传 2/2 · second.txt' })).toBeVisible()
  expect(uploadedFiles).toEqual(['first.txt', 'second.txt'])
  releaseSecondUpload?.()

  await expect(page.getByRole('status').filter({ hasText: '2 个已提交' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: '0 个重复文件已跳过' })).toHaveCount(0)
  await expect(page.locator('.knowledge-document-list').getByText('first.txt', { exact: true })).toBeVisible()
  await expect(page.locator('.knowledge-document-list').getByText('second.txt', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /上传并处理/ })).toHaveCount(0)
})

test('refreshing the document list does not start a duplicate status poll', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let pollCount = 0
  let releasePoll: (() => void) | undefined
  let markPollStarted: (() => void) | undefined
  const pollStarted = new Promise<void>((resolve) => {
    markPollStarted = resolve
  })

  await page.route('**/api/v1/documents?*', (route) =>
    route.fulfill({
      json: {
        items: [{
          id: 'document-pending',
          knowledge_base_id: knowledgeBase.id,
          file_name: 'pending.txt',
          size_bytes: 10,
          status: 'UPLOADED',
        }],
        count: 1,
        knowledge_base_id: knowledgeBase.id,
      },
    }),
  )
  await page.route('**/api/v1/documents/document-pending', async (route) => {
    pollCount += 1
    markPollStarted?.()
    await new Promise<void>((resolve) => {
      releasePoll = resolve
    })
    return route.fulfill({
      json: {
        id: 'document-pending',
        knowledge_base_id: knowledgeBase.id,
        file_name: 'pending.txt',
        size_bytes: 10,
        status: 'UPLOADED',
      },
    })
  })

  await page.goto('/?view=workspace')
  await pollStarted
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect.poll(() => pollCount).toBe(1)
  releasePoll?.()
})

test('a late document-list response cannot replace newer data', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let releaseOldList: (() => void) | undefined
  let markOldListStarted: (() => void) | undefined
  const oldListStarted = new Promise<void>((resolve) => {
    markOldListStarted = resolve
  })
  let listRequest = 0

  await page.route('**/api/v1/documents?*', async (route) => {
    listRequest += 1
    if (listRequest === 2) {
      markOldListStarted?.()
      await new Promise<void>((resolve) => {
        releaseOldList = resolve
      })
      return route.fulfill({
        json: {
          items: [{
            id: 'document-old',
            knowledge_base_id: knowledgeBase.id,
            file_name: '旧列表.txt',
            size_bytes: 3,
            status: 'READY',
          }],
          count: 1,
          knowledge_base_id: knowledgeBase.id,
        },
      })
    }
    if (listRequest === 3) {
      return route.fulfill({
        json: {
          items: [{
            id: 'document-new',
            knowledge_base_id: knowledgeBase.id,
            file_name: '最新列表.txt',
            size_bytes: 3,
            status: 'READY',
          }],
          count: 1,
          knowledge_base_id: knowledgeBase.id,
        },
      })
    }
    return route.fulfill({
      json: { items: [], count: 0, knowledge_base_id: knowledgeBase.id },
    })
  })

  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: '知识库管理 (0)' })).toBeVisible()
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await oldListStarted
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByText('最新列表.txt', { exact: true })).toBeVisible()

  releaseOldList?.()
  await expect(page.getByText('最新列表.txt', { exact: true })).toBeVisible()
  await expect(page.getByText('旧列表.txt', { exact: true })).toHaveCount(0)
})

test('a late document preview cannot replace the currently selected document', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let releaseOldContent: (() => void) | undefined
  let markOldContentStarted: (() => void) | undefined
  const oldContentStarted = new Promise<void>((resolve) => {
    markOldContentStarted = resolve
  })

  await page.route('**/api/v1/documents?*', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'document-old',
            knowledge_base_id: knowledgeBase.id,
            file_name: '旧文档.txt',
            size_bytes: 3,
            status: 'READY',
          },
          {
            id: 'document-new',
            knowledge_base_id: knowledgeBase.id,
            file_name: '当前文档.txt',
            size_bytes: 3,
            status: 'READY',
          },
        ],
        count: 2,
        knowledge_base_id: knowledgeBase.id,
      },
    }),
  )
  await page.route('**/api/v1/documents/document-*/content', async (route) => {
    if (route.request().url().endsWith('/document-old/content')) {
      markOldContentStarted?.()
      await new Promise<void>((resolve) => {
        releaseOldContent = resolve
      })
      return route.fulfill({ contentType: 'text/plain', body: '旧文档正文' })
    }
    return route.fulfill({ contentType: 'text/plain', body: '当前文档正文' })
  })
  await page.route('**/api/v1/documents/document-*/chunks', (route) =>
    route.fulfill({ json: { items: [], count: 0 } }),
  )

  await page.goto('/?view=workspace')
  const documentButtons = page.locator('.knowledge-document-main')
  await documentButtons.nth(0).click()
  await oldContentStarted
  await expect(page.getByRole('button', { name: '关闭资料详情' })).toBeFocused()
  const documentDialog = page.getByRole('dialog')
  const documentFocusableElements = documentDialog.locator(
    'a[href]:visible, button:not([disabled]):visible, input:not([disabled]):visible, select:not([disabled]):visible, textarea:not([disabled]):visible, [tabindex]:not([tabindex="-1"]):visible',
  )
  await page.keyboard.press('Shift+Tab')
  await expect(documentFocusableElements.last()).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(documentFocusableElements.first()).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(documentButtons.nth(0)).toBeFocused()
  await documentButtons.nth(1).click()

  await expect(page.getByRole('dialog').getByRole('heading', { name: '当前文档.txt' })).toBeVisible()
  await expect(page.getByText('当前文档正文', { exact: true })).toBeVisible()
  releaseOldContent?.()
  await expect(page.getByText('当前文档正文', { exact: true })).toBeVisible()
  await expect(page.getByText('旧文档正文', { exact: true })).toHaveCount(0)
})

test('an open document detail reflects processing status updates', async ({ page }) => {
  await page.clock.install()
  await mockAuthenticatedBackend(page)
  let detailRequests = 0
  let markFirstStatusRequest: (() => void) | undefined
  const firstStatusRequest = new Promise<void>((resolve) => {
    markFirstStatusRequest = resolve
  })

  await page.route('**/api/v1/documents?*', (route) =>
    route.fulfill({
      json: {
        items: [{
          id: 'document-processing',
          knowledge_base_id: knowledgeBase.id,
          file_name: 'processing.txt',
          size_bytes: 10,
          status: 'UPLOADED',
        }],
        count: 1,
        knowledge_base_id: knowledgeBase.id,
      },
    }),
  )
  await page.route('**/api/v1/documents/document-processing', (route) => {
    detailRequests += 1
    markFirstStatusRequest?.()
    const status = detailRequests > 1 ? 'READY' : 'UPLOADED'
    return route.fulfill({
      json: {
        id: 'document-processing',
        knowledge_base_id: knowledgeBase.id,
        file_name: 'processing.txt',
        size_bytes: 10,
        status,
      },
    })
  })
  await page.route('**/api/v1/documents/document-processing/content', (route) =>
    route.fulfill({ contentType: 'text/plain', body: 'Processing document text' }),
  )
  await page.route('**/api/v1/documents/document-processing/chunks', (route) =>
    route.fulfill({ json: { items: [], count: 0 } }),
  )

  await page.goto('/?view=workspace')
  await firstStatusRequest
  await page.locator('.knowledge-document-main').click()
  const detail = page.getByRole('dialog')
  await expect(detail.getByText('已上传', { exact: true })).toBeVisible()
  await page.clock.runFor(2000)
  await expect(detail.getByText('可检索', { exact: true })).toBeVisible()
})

test('a failed status check can be resumed manually', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let detailRequests = 0

  await page.route('**/api/v1/documents?*', (route) =>
    route.fulfill({
      json: {
        items: [{
          id: 'document-recover',
          knowledge_base_id: knowledgeBase.id,
          file_name: 'recover.txt',
          size_bytes: 10,
          status: 'UPLOADED',
        }],
        count: 1,
        knowledge_base_id: knowledgeBase.id,
      },
    }),
  )
  await page.route('**/api/v1/documents/document-recover', (route) => {
    detailRequests += 1
    if (detailRequests === 1) {
      return route.fulfill({ status: 503, json: { detail: '暂时无法检查文档状态' } })
    }
    return route.fulfill({
      json: {
        id: 'document-recover',
        knowledge_base_id: knowledgeBase.id,
        file_name: 'recover.txt',
        size_bytes: 10,
        status: 'READY',
      },
    })
  })

  await page.goto('/?view=workspace')
  await expect(page.getByRole('button', { name: '检查状态' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: '自动状态检查已暂停' })).toBeVisible()
  await page.getByRole('button', { name: '检查状态' }).click()
  await expect(page.getByText('可检索', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '检查状态' })).toHaveCount(0)
  await expect(page.getByText('暂时无法检查文档状态')).toHaveCount(0)
})

test('a stalled document poll can be resumed after the timeout notice', async ({ page }) => {
  test.setTimeout(60_000)
  await page.clock.install()
  await mockAuthenticatedBackend(page)
  let detailRequests = 0
  let markFirstDetailRequest: (() => void) | undefined
  const firstDetailRequest = new Promise<void>((resolve) => {
    markFirstDetailRequest = resolve
  })

  await page.route('**/api/v1/documents?*', (route) =>
    route.fulfill({
      json: {
        items: [{
          id: 'document-slow',
          knowledge_base_id: knowledgeBase.id,
          file_name: 'slow.txt',
          size_bytes: 10,
          status: 'UPLOADED',
        }],
        count: 1,
        knowledge_base_id: knowledgeBase.id,
      },
    }),
  )
  await page.route('**/api/v1/documents/document-slow', (route) => {
    detailRequests += 1
    markFirstDetailRequest?.()
    const status = detailRequests > 180 ? 'READY' : 'UPLOADED'
    return route.fulfill({
      json: {
        id: 'document-slow',
        knowledge_base_id: knowledgeBase.id,
        file_name: 'slow.txt',
        size_bytes: 10,
        status,
      },
    })
  })

  await page.goto('/?view=workspace')
  await firstDetailRequest
  for (let interval = 0; interval < 2000 && detailRequests < 180; interval += 1) {
    await page.clock.runFor(2000)
  }
  expect(detailRequests).toBe(180)

  await expect(page.getByRole('status').filter({ hasText: '自动状态检查已暂停' })).toBeVisible()
  await expect(page.getByRole('button', { name: '检查状态' })).toBeVisible()
  await page.getByRole('button', { name: '检查状态' }).click()
  await expect(page.getByText('可检索', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '检查状态' })).toHaveCount(0)
})

test('user can ask a knowledge-base question and see streamed answer', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  let unexpectedConversationRestoreCount = 0
  await page.route('**/api/v1/conversations/conversation-e2e', (route) => {
    unexpectedConversationRestoreCount += 1
    return route.fulfill({ status: 500, json: { detail: 'Unexpected restore' } })
  })
  await page.route('**/api/v1/notes', (route) =>
    route.fulfill({
      status: 201,
      json: {
        id: 'saved-answer-note',
        user_id: user.id,
        knowledge_base_id: knowledgeBase.id,
        source_document_id: null,
        title: 'MCP 是什么？',
        content: '这是测试回答。',
        metadata: {},
        created_at: '2026-10-20T10:00:00Z',
        updated_at: '2026-10-20T10:00:00Z',
      },
    }),
  )
  await page.route('**/api/v1/agent/chat/stream', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'event: token',
        'data: {"type":"token","content":"这是"}',
        '',
        'event: token',
        'data: {"type":"token","content":"测试回答。"}',
        '',
        'event: done',
        'data: {"type":"done","conversation_id":"conversation-e2e","sources":[]}',
        '',
      ].join('\n'),
    }),
  )

  await page.goto('/?view=welcome')
  await page.getByRole('button', { name: 'AI 对话' }).click()
  await expect(page.getByRole('heading', { name: 'AI 对话' })).toBeVisible()

  await page.getByPlaceholder('随心输入').fill('MCP 是什么？')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('这是测试回答。')).toBeVisible()
  await expect(page.getByText('回答完成')).toBeVisible()
  expect(await page.evaluate(() =>
    window.localStorage.getItem('rag_notebook_chat_draft:e2e@example.com'),
  )).toBeNull()
  expect(unexpectedConversationRestoreCount).toBe(0)
  const messageActions = page.locator('.chat-message-actions')
  const actionGap = await messageActions.evaluate((element) =>
    Number.parseFloat(getComputedStyle(element).columnGap),
  )
  expect(actionGap).toBeGreaterThanOrEqual(8)
  await page.getByRole('button', { name: '复制回答' }).click()
  await expect(page.getByRole('button', { name: '已复制' })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('这是测试回答。')
  await page.getByRole('button', { name: '保存为笔记' }).click()
  await expect(page.getByRole('button', { name: '已保存为笔记' })).toBeVisible()
})

test('chat restores an unsent question after the page reloads', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.goto('/?view=chat')

  const composer = page.locator('.chat-composer-row textarea')
  await expect(composer).toBeVisible()
  await composer.fill('刷新后仍要保留的提问')
  await expect.poll(() => page.evaluate(() =>
    window.localStorage.getItem('rag_notebook_chat_draft:e2e@example.com'),
  )).toBe('刷新后仍要保留的提问')

  await page.reload()
  await expect(page.locator('.chat-composer-row textarea')).toHaveValue('刷新后仍要保留的提问')
})

test('chat shows elapsed time while the response is pending', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let releaseResponse: (() => void) | undefined
  let markRequestStarted: (() => void) | undefined
  const requestStarted = new Promise<void>((resolve) => {
    markRequestStarted = resolve
  })

  await page.route('**/api/v1/agent/chat/stream', async (route) => {
    markRequestStarted?.()
    await new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'event: token',
        'data: {"type":"token","content":"慢请求完成。"}',
        '',
        'event: done',
        'data: {"type":"done","conversation_id":"timed-chat-e2e"}',
        '',
      ].join('\n'),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'AI 对话' }).click()
  await page.getByPlaceholder('随心输入').fill('请回答一个需要较长时间的问题')
  await page.getByRole('button', { name: '发送' }).click()
  await requestStarted
  await expect(page.getByText('00:01')).toBeVisible({ timeout: 2500 })

  releaseResponse?.()
  await expect(page.getByText('慢请求完成。')).toBeVisible()
  await expect(page.locator('.chat-elapsed-time')).toHaveCount(0)
})

test('confirming an IME candidate does not send the chat message', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let requestCount = 0
  await page.route('**/api/v1/agent/chat/stream', (route) => {
    requestCount += 1
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'event: token',
        'data: {"type":"token","content":"收到。"}',
        '',
        'event: done',
        'data: {"type":"done","conversation_id":"ime-conversation-e2e"}',
        '',
      ].join('\n'),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'AI 对话' }).click()
  const composer = page.getByPlaceholder('随心输入')
  await composer.fill('中文输入法测试')
  await composer.dispatchEvent('compositionstart')
  await composer.dispatchEvent('keydown', {
    key: 'Enter',
    code: 'Enter',
    keyCode: 13,
    which: 13,
    isComposing: true,
    bubbles: true,
    cancelable: true,
  })

  expect(requestCount).toBe(0)
  await composer.dispatchEvent('compositionend')
  await composer.press('Enter')
  await expect(page.getByText('收到。')).toBeVisible()
  expect(requestCount).toBe(1)
})

test('chat composer grows for multiline prompts and scrolls after reaching its limit', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'AI 对话' }).click()

  const composer = page.getByPlaceholder('随心输入')
  await composer.fill('第一行问题\n第二行补充背景')
  const multilineHeight = await composer.evaluate((element) => element.getBoundingClientRect().height)
  expect(multilineHeight).toBeGreaterThan(48)

  await composer.fill(Array.from({ length: 30 }, (_, index) => `补充背景 ${index + 1}`).join('\n'))
  const cappedSize = await composer.evaluate((element) => ({
    height: element.getBoundingClientRect().height,
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
  }))
  expect(cappedSize.height).toBeLessThanOrEqual(150)
  expect(cappedSize.scrollHeight).toBeGreaterThan(cappedSize.clientHeight)
})

test('chat follows the newest streamed content when the reader is at the bottom', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  const longAnswer = Array.from(
    { length: 36 },
    (_, index) => `第 ${index + 1} 段回答内容，用来验证长消息会自动滚动到最新位置。`,
  ).join('\n\n')

  await page.route('**/api/v1/agent/chat/stream', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'event: token',
        `data: ${JSON.stringify({ type: 'token', content: longAnswer })}`,
        '',
        'event: done',
        'data: {"type":"done","conversation_id":"long-answer-conversation"}',
        '',
      ].join('\n'),
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'AI 对话' }).click()
  await page.getByPlaceholder('随心输入').fill('给我一份详细说明')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText(/第 36 段回答内容/)).toBeVisible()
  const scrollPosition = await page.locator('.chat-message-list').evaluate((element) => ({
    top: element.scrollTop,
    bottom: element.scrollHeight - element.clientHeight,
  }))
  expect(scrollPosition.top).toBeGreaterThanOrEqual(scrollPosition.bottom - 2)
})

test('user can use agent streaming, inspect tool steps, and restore the conversation', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.route('**/api/v1/agent/chat/stream', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'event: tool_start',
        'data: {"type":"tool_start","step":1,"server_name":"github","tool_name":"search_repositories","arguments":{"query":"modelcontextprotocol"},"is_error":false,"result_preview":""}',
        '',
        'event: tool_result',
        'data: {"type":"tool_result","step":1,"server_name":"github","tool_name":"search_repositories","arguments":{"query":"modelcontextprotocol"},"is_error":false,"result_preview":"5 repositories found"}',
        '',
        'event: token',
        'data: {"type":"token","content":"GitHub 查询完成。"}',
        '',
        'event: done',
        'data: {"type":"done","conversation_id":"agent-conversation-e2e","tool_steps":[{"step":1,"server_name":"github","tool_name":"search_repositories","arguments":{"query":"modelcontextprotocol"},"is_error":false,"result_preview":"5 repositories found"}]}',
        '',
      ].join('\n'),
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'AI 对话' }).click()
  const streamToggle = page.getByRole('button', { name: '流式输出' })
  await expect(streamToggle).toBeEnabled()

  await page.getByPlaceholder('随心输入').fill('搜索 MCP 相关仓库')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('GitHub 查询完成。')).toBeVisible()
  await expect(page.getByText('回答完成')).toBeVisible()
  await page.getByText('已调用 1 个工具').click()
  await expect(page.getByText('github · search_repositories')).toBeVisible()
  await expect(page.getByText('完成', { exact: true })).toBeVisible()

  await page.route('**/api/v1/conversations/agent-conversation-e2e', (route) =>
    route.fulfill({
      json: {
        conversation: {
          id: 'agent-conversation-e2e',
          knowledge_base_id: knowledgeBase.id,
          title: '搜索 MCP 相关仓库',
          model_name: 'deepseek-chat',
          created_at: '2026-08-22T10:00:00Z',
          updated_at: '2026-08-22T10:01:00Z',
          message_count: 2,
        },
        messages: [
          {
            id: 'agent-user-message',
            conversation_id: 'agent-conversation-e2e',
            role: 'user',
            content: '搜索 MCP 相关仓库',
            citations: [],
            metadata: {},
            created_at: '2026-08-22T10:00:00Z',
          },
          {
            id: 'agent-assistant-message',
            conversation_id: 'agent-conversation-e2e',
            role: 'assistant',
            content: 'GitHub 查询完成。',
            citations: [],
            metadata: {
              retrieval_mode: 'agent',
              tool_steps: [{
                step: 1,
                server_name: 'github',
                tool_name: 'search_repositories',
                arguments: { query: 'modelcontextprotocol' },
                is_error: false,
                result_preview: '5 repositories found',
              }],
            },
            created_at: '2026-08-22T10:01:00Z',
          },
        ],
      },
    }),
  )
  await page.route(/\/api\/v1\/conversations(?:\?.*)?$/, (route) =>
    route.fulfill({
      json: {
        items: [{
          id: 'agent-conversation-e2e',
          knowledge_base_id: knowledgeBase.id,
          title: '搜索 MCP 相关仓库',
          model_name: 'deepseek-chat',
          created_at: '2026-08-22T10:00:00Z',
          updated_at: '2026-08-22T10:01:00Z',
          message_count: 2,
        }],
        count: 1,
      },
    }),
  )

  await page.getByRole('button', { name: '会话管理' }).click()
  await page.getByRole('button', { name: /搜索 MCP 相关仓库/ }).click()
  await expect(page.getByText('GitHub 查询完成。')).toBeVisible()
  await expect(page.getByText('已调用 1 个工具')).toBeVisible()
})

test('user can retry a failed agent stream', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let attempts = 0
  await page.route('**/api/v1/agent/chat/stream', (route) => {
    attempts += 1
    const body = attempts === 1
      ? [
          'event: error',
          'data: {"type":"error","message":"GitHub 暂时不可用","retryable":true,"tool_steps":[]}',
          '',
        ].join('\n')
      : [
          'event: token',
          'data: {"type":"token","content":"重试成功。"}',
          '',
          'event: done',
          'data: {"type":"done","conversation_id":"retry-conversation-e2e","tool_steps":[]}',
          '',
        ].join('\n')

    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'AI 对话' }).click()
  await page.getByPlaceholder('随心输入').fill('查询 GitHub')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('GitHub 暂时不可用')).toBeVisible()
  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('重试成功。')).toBeVisible()
  await expect(page.getByText('回答完成')).toBeVisible()
  expect(attempts).toBe(2)
})

test('user can retry an interrupted answer after restoring its conversation', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let retryPayload: Record<string, unknown> | undefined

  await page.route('**/api/v1/conversations/interrupted-conversation', (route) =>
    route.fulfill({
      json: {
        conversation: {
          id: 'interrupted-conversation',
          knowledge_base_id: knowledgeBase.id,
          title: '查询 MCP 文档',
          model_name: 'deepseek-chat',
          created_at: '2026-10-20T10:00:00Z',
          updated_at: '2026-10-20T10:01:00Z',
          message_count: 2,
        },
        messages: [
          {
            id: 'interrupted-user-message',
            conversation_id: 'interrupted-conversation',
            role: 'user',
            content: '查询 MCP 文档',
            citations: [],
            metadata: {},
            created_at: '2026-10-20T10:00:00Z',
          },
          {
            id: 'interrupted-assistant-message',
            conversation_id: 'interrupted-conversation',
            role: 'assistant',
            content: '已经找到一部分资料。',
            citations: [],
            metadata: {
              status: 'FAILED',
              error_message: '生成已停止',
              retryable: true,
            },
            created_at: '2026-10-20T10:01:00Z',
          },
        ],
      },
    }),
  )
  await page.route('**/api/v1/agent/chat/stream', (route) => {
    retryPayload = route.request().postDataJSON() as Record<string, unknown>
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'event: token',
        'data: {"type":"token","content":"重新生成完成。"}',
        '',
        'event: done',
        'data: {"type":"done","conversation_id":"interrupted-conversation"}',
        '',
      ].join('\n'),
    })
  })

  await page.goto('/?view=chat&conversation_id=interrupted-conversation')
  await expect(page.getByText('已经找到一部分资料。')).toBeVisible()
  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('重新生成完成。')).toBeVisible()
  expect(retryPayload?.question).toBe('查询 MCP 文档')
  expect(retryPayload?.conversation_id).toBe('interrupted-conversation')
})

test('opening a new chat ignores a conversation restore that finishes late', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  const conversationId = '11111111-1111-4111-8111-111111111111'
  let releaseRestore: (() => void) | undefined
  let markRestoreStarted: (() => void) | undefined
  const restoreStarted = new Promise<void>((resolve) => {
    markRestoreStarted = resolve
  })

  await page.route(`**/api/v1/conversations/${conversationId}`, async (route) => {
    markRestoreStarted?.()
    await new Promise<void>((resolve) => {
      releaseRestore = resolve
    })
    await route.fulfill({
      json: {
        conversation: {
          id: conversationId,
          knowledge_base_id: knowledgeBase.id,
          title: '旧会话',
          model_name: 'deepseek-chat',
          created_at: '2026-10-20T10:00:00Z',
          updated_at: '2026-10-20T10:01:00Z',
          message_count: 2,
        },
        messages: [
          {
            id: 'late-user-message',
            conversation_id: conversationId,
            role: 'user',
            content: '旧会话问题',
            citations: [],
            metadata: {},
            created_at: '2026-10-20T10:00:00Z',
          },
          {
            id: 'late-assistant-message',
            conversation_id: conversationId,
            role: 'assistant',
            content: '迟到的旧回答',
            citations: [],
            metadata: {},
            created_at: '2026-10-20T10:01:00Z',
          },
        ],
      },
    })
  })

  await page.goto(`/?view=chat&conversation_id=${conversationId}`)
  await restoreStarted
  await page.getByRole('button', { name: '新建对话' }).click()
  await expect(page.getByText('开始向知识库提问')).toBeVisible()

  releaseRestore?.()
  await expect(page.getByText('迟到的旧回答')).not.toBeVisible()
})

test('restoring a conversation clears stale content and shows a loading state', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  const conversationId = '22222222-2222-4222-8222-222222222222'
  let releaseRestore: (() => void) | undefined
  let markRestoreStarted: (() => void) | undefined
  const restoreStarted = new Promise<void>((resolve) => {
    markRestoreStarted = resolve
  })

  await page.route(`**/api/v1/conversations/${conversationId}`, async (route) => {
    markRestoreStarted?.()
    await new Promise<void>((resolve) => {
      releaseRestore = resolve
    })
    await route.fulfill({
      json: {
        conversation: {
          id: conversationId,
          knowledge_base_id: knowledgeBase.id,
          title: '正在恢复的会话',
          model_name: 'deepseek-chat',
          created_at: '2026-10-20T10:00:00Z',
          updated_at: '2026-10-20T10:01:00Z',
          message_count: 2,
        },
        messages: [
          {
            id: 'restoring-user-message',
            conversation_id: conversationId,
            role: 'user',
            content: '恢复后的问题',
            citations: [],
            metadata: {},
            created_at: '2026-10-20T10:00:00Z',
          },
          {
            id: 'restoring-assistant-message',
            conversation_id: conversationId,
            role: 'assistant',
            content: '恢复后的回答',
            citations: [],
            metadata: {},
            created_at: '2026-10-20T10:01:00Z',
          },
        ],
      },
    })
  })

  await page.goto(`/?view=chat&conversation_id=${conversationId}`)
  await restoreStarted
  await expect(page.locator('.chat-message-list').getByText('正在恢复会话')).toBeVisible()
  await expect(page.getByText('开始向知识库提问')).not.toBeVisible()

  releaseRestore?.()
  await expect(page.getByText('恢复后的回答')).toBeVisible()
})

test('user can retry restoring a conversation after a temporary failure', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  const conversationId = '33333333-3333-4333-8333-333333333333'
  let attempts = 0
  await page.route(`**/api/v1/conversations/${conversationId}`, (route) => {
    attempts += 1
    if (attempts === 1) {
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '会话服务暂时不可用' }),
      })
    }

    return route.fulfill({
      json: {
        conversation: {
          id: conversationId,
          knowledge_base_id: knowledgeBase.id,
          title: '可恢复的会话',
          model_name: 'deepseek-chat',
          created_at: '2026-10-20T10:00:00Z',
          updated_at: '2026-10-20T10:01:00Z',
          message_count: 2,
        },
        messages: [
          {
            id: 'retry-restore-user',
            conversation_id: conversationId,
            role: 'user',
            content: '继续上次的讨论',
            citations: [],
            metadata: {},
            created_at: '2026-10-20T10:00:00Z',
          },
          {
            id: 'retry-restore-assistant',
            conversation_id: conversationId,
            role: 'assistant',
            content: '已成功恢复。',
            citations: [],
            metadata: {},
            created_at: '2026-10-20T10:01:00Z',
          },
        ],
      },
    })
  })

  await page.goto(`/?view=chat&conversation_id=${conversationId}`)
  await expect(page.locator('.chat-message-list').getByText('会话暂时无法恢复')).toBeVisible()
  await expect(page.getByText('会话服务暂时不可用')).toBeVisible()
  await page.getByRole('button', { name: '重试恢复' }).click()
  await expect(page.getByText('已成功恢复。')).toBeVisible()
  expect(attempts).toBe(2)
})

test('double-clicking finish records a daily review only once', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let finishRequests = 0
  let releaseFinish: (() => void) | undefined
  let markFinishStarted: (() => void) | undefined
  const finishStarted = new Promise<void>((resolve) => {
    markFinishStarted = resolve
  })

  await page.route('**/api/v1/reviews/today', (route) =>
    route.fulfill({
      json: {
        total_count: 1,
        reviews: [{
          review_id: 'review-e2e',
          note_id: 'note-e2e',
          title: 'Agent 记忆',
          content_preview: 'Agent 如何保留对话上下文？',
          review_count: 0,
          last_reviewed_at: null,
          interval_days: 1,
        }],
      },
    }),
  )
  await page.route('**/api/v1/reviews/stats', (route) =>
    route.fulfill({
      json: {
        total_notes: 1,
        tracked_notes: 1,
        reviewed_notes: 0,
        due_count: 1,
        total_review_count: 0,
        recent_reviewed_notes: 0,
        recent_review_count: 0,
        last_reviewed_at: null,
        next_review_at: null,
      },
    }),
  )
  await page.route('**/api/v1/reviews/history?*', (route) =>
    route.fulfill({ json: { events: [], daily_counts: [], days: 30, total_count: 0 } }),
  )
  await page.route('**/api/v1/reviews/question/note-e2e', (route) =>
    route.fulfill({
      json: {
        question: 'Agent 如何保留对话上下文？',
        choices: ['保存消息历史', '清空上下文'],
        answer: '保存消息历史',
      },
    }),
  )
  await page.route('**/api/v1/reviews/done/note-e2e', async (route) => {
    finishRequests += 1
    markFinishStarted?.()
    await new Promise<void>((resolve) => {
      releaseFinish = resolve
    })
    return route.fulfill({ json: { success: true, message: 'Review saved' } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '每日回顾', exact: true }).click()
  await page.getByRole('button', { name: '开始回顾' }).click()
  await page.getByRole('button', { name: /保存消息历史/ }).click()
  const finishButton = page.getByRole('button', { name: '完成回顾' })
  await finishButton.dblclick()
  await finishStarted
  await expect(page.getByRole('button', { name: '正在记录……' })).toBeDisabled()
  expect(finishRequests).toBe(1)

  releaseFinish?.()
  await expect(page.getByText('今日回顾已完成')).toBeVisible()
  expect(finishRequests).toBe(1)
})

test('archiving a session locks its actions until the update completes', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let archiveRequests = 0
  let releaseArchive: (() => void) | undefined
  let markArchiveStarted: (() => void) | undefined
  const archiveStarted = new Promise<void>((resolve) => {
    markArchiveStarted = resolve
  })

  const session = {
    id: 'conversation-archive-e2e',
    knowledge_base_id: knowledgeBase.id,
    title: 'Agent 记忆测试',
    model_name: 'deepseek-chat',
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-20T10:01:00Z',
    message_count: 2,
    archived_at: null,
  }

  await page.route('**/api/v1/conversations**', async (route) => {
    if (route.request().method() === 'PATCH') {
      archiveRequests += 1
      markArchiveStarted?.()
      await new Promise<void>((resolve) => {
        releaseArchive = resolve
      })
      return route.fulfill({
        json: { ...session, archived_at: '2026-10-20T10:02:00Z' },
      })
    }
    return route.fulfill({ json: { items: [session], count: 1 } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '会话管理' }).click()
  const card = page.locator('.session-card').filter({ hasText: 'Agent 记忆测试' })
  const archiveButton = card.getByRole('button', { name: '归档' })
  await archiveButton.click()
  await archiveStarted
  await expect(card.getByRole('button', { name: '正在更新……' })).toBeDisabled()
  expect(archiveRequests).toBe(1)

  releaseArchive?.()
  await expect(card).toHaveCount(0)
  expect(archiveRequests).toBe(1)
})

test('an archived session stays visible when the archive filter changes during the update', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let releaseArchive: (() => void) | undefined
  let markArchiveStarted: (() => void) | undefined
  const archiveStarted = new Promise<void>((resolve) => {
    markArchiveStarted = resolve
  })

  const session = {
    id: 'conversation-filter-race-e2e',
    knowledge_base_id: knowledgeBase.id,
    title: '筛选竞态会话',
    model_name: 'deepseek-chat',
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-20T10:01:00Z',
    message_count: 2,
    archived_at: null,
  }
  const archivedSession = { ...session, archived_at: '2026-10-20T10:02:00Z' }

  await page.route('**/api/v1/conversations**', async (route) => {
    if (route.request().method() === 'PATCH') {
      markArchiveStarted?.()
      await new Promise<void>((resolve) => {
        releaseArchive = resolve
      })
      return route.fulfill({ json: archivedSession })
    }
    const includeArchived = new URL(route.request().url()).searchParams.get('include_archived') === 'true'
    return route.fulfill({
      json: { items: [includeArchived ? archivedSession : session], count: 1 },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '会话管理' }).click()
  const card = page.locator('.session-card').filter({ hasText: '筛选竞态会话' })
  await card.getByRole('button', { name: '归档' }).click()
  await archiveStarted
  await page.getByRole('checkbox', { name: '显示已归档' }).check()
  await expect(card).toBeVisible()

  releaseArchive?.()
  await expect(card).toBeVisible()
})

test('a stale session-list response cannot undo a completed archive action', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  let listRequests = 0
  let releaseStaleList: (() => void) | undefined
  let markStaleListStarted: (() => void) | undefined
  let releaseArchive: (() => void) | undefined
  let markArchiveStarted: (() => void) | undefined
  const staleListStarted = new Promise<void>((resolve) => {
    markStaleListStarted = resolve
  })
  const archiveStarted = new Promise<void>((resolve) => {
    markArchiveStarted = resolve
  })

  const session = {
    id: 'conversation-stale-list-e2e',
    knowledge_base_id: knowledgeBase.id,
    title: '旧列表竞态会话',
    model_name: 'deepseek-chat',
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-20T10:01:00Z',
    message_count: 2,
    archived_at: null,
  }
  const archivedSession = { ...session, archived_at: '2026-10-20T10:02:00Z' }

  await page.route('**/api/v1/conversations**', async (route) => {
    if (route.request().method() === 'PATCH') {
      markArchiveStarted?.()
      await new Promise<void>((resolve) => {
        releaseArchive = resolve
      })
      return route.fulfill({ json: archivedSession })
    }
    listRequests += 1
    if (listRequests === 1) {
      return route.fulfill({ json: { items: [session], count: 1 } })
    }
    markStaleListStarted?.()
    await new Promise<void>((resolve) => {
      releaseStaleList = resolve
    })
    return route.fulfill({ json: { items: [session], count: 1 } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '会话管理' }).click()
  const card = page.locator('.session-card').filter({ hasText: '旧列表竞态会话' })
  await card.getByRole('button', { name: '归档' }).click()
  await archiveStarted
  await page.getByRole('checkbox', { name: '显示已归档' }).check()
  await staleListStarted

  releaseArchive?.()
  await expect(card).toBeVisible()
  releaseStaleList?.()
  await expect(card).toBeVisible()
})

test('user can open session management from the sidebar', async ({ page }) => {
  await mockAuthenticatedBackend(page)
  await page.route('**/api/v1/conversations**', (route) =>
    route.fulfill({ json: { items: [], count: 0 } }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: '会话管理' }).click()
  await expect(page.getByRole('heading', { name: '会话管理' })).toBeVisible()
  await expect(page.getByText('还没有会话')).toBeVisible()
})
