import {
  Suspense,
  useCallback,
  useEffect,
  lazy,
  useMemo,
  useRef,
  useState,
} from 'react'

import type {
  FormEvent,
} from 'react'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import '../App.css'

import {
  apiRequest,
} from '../api/client'

import {
  autocompleteNote,
  createNote,
  createNoteTemplate,
  deleteNote,   // ✨ 新增
  deleteNoteTemplate,
  assistNoteStream,
  getNote,
  getNoteTemplates,
  retryNoteIndex,
  updateNoteTemplate,
  searchNotes,
  updateNote,   // ✨ 新增
  type WritingAssistAction,
} from '../api/notes'

import NotebookShell, {
  type NotebookView,
} from '../components/NotebookShell'
import { useLanguage } from '../i18n'
const RichNoteEditor = lazy(() => import('../components/RichNoteEditor'))

import type {
  RichNoteEditorHandle,
} from '../components/RichNoteEditor'

import type {
  KnowledgeBase,
} from '../types'

import type {
  NoteTemplate,
  NoteResponse,
} from '../types/notes'

type NotesPageProps = {
  email?: string
  onLogout?: () => void
  onNavigate?: (
    view: NotebookView,
  ) => void
}

type NoteCategory = {
  label: string
  value: string
}

type LocalNoteTemplate = {
  id: string
  name: string
  title: string
  content: string
  category: string
  tags: string
}

type NoteDraft = {
  title: string
  content: string
  category: string
  tags: string
}

type OutlineItem = {
  level: number
  text: string
}

const NOTE_TEMPLATES_KEY = 'rag_notebook_note_templates'
const NOTE_DRAFT_KEY = 'rag_notebook_note_draft'

function readLocalTemplates(): LocalNoteTemplate[] {
  try {
    const raw = localStorage.getItem(NOTE_TEMPLATES_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function readNoteDraft(storageKey: string): NoteDraft | null {
  try {
    const raw = localStorage.getItem(storageKey)
    return raw ? JSON.parse(raw) as NoteDraft : null
  } catch {
    return null
  }
}

function extractOutline(markdown: string): OutlineItem[] {
  return markdown
    .split(/\r?\n/)
    .map((line) => {
      const match = /^(#{1,3})\s+(.+?)\s*$/.exec(line)
      return match
        ? { level: match[1].length, text: match[2] }
        : null
    })
    .filter((item): item is OutlineItem => item !== null)
    .slice(0, 80)
}

const LOCAL_METADATA_RULES: Array<{
  category: string
  keywords: string[]
  tags: string[]
}> = [
  { category: 'technology', keywords: ['代码', 'api', 'mcp', 'rag', 'python', 'typescript', '数据库'], tags: ['技术'] },
  { category: 'study', keywords: ['学习', '课程', '复习', '笔记', '考试', '知识'], tags: ['学习'] },
  { category: 'work', keywords: ['项目', '会议', '客户', '需求', '工作', '计划'], tags: ['工作'] },
  { category: 'life', keywords: ['生活', '旅行', '健康', '购物', '家庭', '日记'], tags: ['生活'] },
]

function suggestLocalMetadata(title: string, content: string) {
  const source = `${title} ${content}`.toLowerCase()
  const matched = LOCAL_METADATA_RULES
    .map((rule) => ({
      rule,
      score: rule.keywords.filter((keyword) => source.includes(keyword)).length,
    }))
    .sort((left, right) => right.score - left.score)
  const best = matched[0]
  const tags = matched
    .filter((item) => item.score > 0)
    .flatMap((item) => item.rule.tags)

  return {
    category: best && best.score > 0 ? best.rule.category : 'other',
    tags: Array.from(new Set(tags)).slice(0, 5),
  }
}

const CATEGORIES: NoteCategory[] = [
  {
    label: '全部',
    value: '',
  },
  {
    label: '工作',
    value: 'work',
  },
  {
    label: '学习',
    value: 'study',
  },
  {
    label: '生活',
    value: 'life',
  },
  {
    label: '技术',
    value: 'technology',
  },
  {
    label: '其他',
    value: 'other',
  },
]

const CATEGORY_LABELS: Record<
  string,
  string
> = {
  work: '工作',
  study: '学习',
  life: '生活',
  technology: '技术',
  other: '其他',
}

function formatDate(value: string, language: 'zh-CN' | 'en-US') {
  return new Date(value).toLocaleDateString(
    language,
    {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    },
  )
}

function getMetadataValue(
  note: NoteResponse,
  key: string,
) {
  const value = note.metadata?.[key]

  return typeof value === 'string'
    ? value
    : ''
}

function getNoteCategory(
  note: NoteResponse,
) {
  return getMetadataValue(note, 'category')
}

function getNoteTags(
  note: NoteResponse,
) {
  const value = note.metadata?.tags

  if (!Array.isArray(value)) {
    return []
  }

  return value.filter(
    (tag): tag is string =>
      typeof tag === 'string' &&
      tag.trim().length > 0,
  )
}

function getPreview(content: string) {
  const text = content
    .replace(/[#*_>`~-]/g, '')
    .replace(/\s+/g, ' ')
    .trim()

  return text.length > 180
    ? `${text.slice(0, 180)}...`
    : text
}

function normalizeNotes(
  value: unknown,
) {
  if (Array.isArray(value)) {
    return value as NoteResponse[]
  }

  if (
    typeof value === 'object' &&
    value !== null &&
    'items' in value &&
    Array.isArray(
      (value as { items?: unknown }).items,
    )
  ) {
    return (
      (value as {
        items: NoteResponse[]
      }).items
    )
  }

  if (
    typeof value === 'object' &&
    value !== null &&
    'notes' in value &&
    Array.isArray(
      (value as { notes?: unknown }).notes,
    )
  ) {
    return (
      (value as {
        notes: NoteResponse[]
      }).notes
    )
  }

  return []
}

function NotesPage({
  email,
  onLogout,
  onNavigate,
}: NotesPageProps) {
  const { language, t } = useLanguage()
  const noteDraftStorageKey = `${NOTE_DRAFT_KEY}:${email?.trim().toLowerCase() || 'anonymous'}`
  const [
    knowledgeBaseId,
    setKnowledgeBaseId,
  ] = useState('')

  const [notes, setNotes] =
    useState<NoteResponse[]>([])

  const [searchQuery, setSearchQuery] =
    useState('')

  const [category, setCategory] =
    useState('')

  const [loading, setLoading] =
    useState(false)

  const notesRequestId = useRef(0)

  const [saving, setSaving] =
    useState(false)

  const [errorMessage, setErrorMessage] =
    useState('')

  const [showEditor, setShowEditor] =
    useState(false)

  const [templates, setTemplates] =
    useState<NoteTemplate[]>([])

  const [draftStatus, setDraftStatus] =
    useState('')

  const [selectedNote, setSelectedNote] =
    useState<NoteResponse | null>(null)

  const selectedNoteId = selectedNote?.id

  // ✨ 新增编辑状态
  const [editingNote, setEditingNote] =
    useState(false)

  const [editTitle, setEditTitle] =
    useState('')

  const [editContent, setEditContent] =
    useState('')

  const [editCategory, setEditCategory] =
    useState('')

  const [editTagsInput, setEditTagsInput] =
    useState('')

  const richEditorRef =
    useRef<RichNoteEditorHandle | null>(null)

  const closeSelectedNoteRef = useRef<() => void>(() => undefined)
  const noteDetailTriggerIdRef = useRef<string | null>(null)
  const noteDetailCloseButtonRef = useRef<HTMLButtonElement | null>(null)

  const [tabCompletionVisible, setTabCompletionVisible] =
    useState(false)

  const [outlineVisible, setOutlineVisible] =
    useState(false)

  const [tabCompletionLoading, setTabCompletionLoading] =
    useState(false)

  const [writingAssistOutput, setWritingAssistOutput] =
    useState('')

  const [writingAssistAction, setWritingAssistAction] =
    useState<WritingAssistAction | null>(null)

  const [writingAssistLoading, setWritingAssistLoading] =
    useState(false)

  const [writingAssistError, setWritingAssistError] =
    useState('')

  const assistAbortRef =
    useRef<AbortController | null>(null)

  const [detailSaving, setDetailSaving] =
    useState(false)

  const [retryingNoteId, setRetryingNoteId] =
    useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [content, setContent] =
    useState('')

  const [noteCategory, setNoteCategory] =
    useState('')

  const [tagsInput, setTagsInput] =
    useState('')

  const [showTemplatePicker, setShowTemplatePicker] =
    useState(false)

  const [editingTemplateId, setEditingTemplateId] =
    useState<string | null>(null)

  const loadKnowledgeBases = useCallback(
    async () => {
      try {
        const result =
          await apiRequest<KnowledgeBase>(
            '/api/v1/knowledge-bases/current',
          )

        if (result) {
          setKnowledgeBaseId(
            (current) =>
              current || result.id,
          )
        }
      } catch (error) {
        setErrorMessage(
          error instanceof Error
            ? error.message
            : '无法加载知识库',
        )
      }
    },
    [],
  )

  const loadTemplates = useCallback(
    async () => {
      const legacyTemplates = readLocalTemplates()
      if (legacyTemplates.length > 0) {
        setTemplates(legacyTemplates)
      }

      try {
        const remoteTemplates = await getNoteTemplates()

        if (remoteTemplates.length === 0 && legacyTemplates.length > 0) {
          const migratedTemplates: NoteTemplate[] = []
          for (const template of legacyTemplates) {
            migratedTemplates.push(
              await createNoteTemplate({
                name: template.name,
                title: template.title,
                content: template.content,
                category: template.category,
                tags: template.tags,
              }),
            )
          }
          setTemplates(migratedTemplates)
        } else {
          setTemplates(remoteTemplates)
        }

        localStorage.removeItem(NOTE_TEMPLATES_KEY)
      } catch (error) {
        if (legacyTemplates.length === 0) {
          setErrorMessage(
            error instanceof Error
              ? error.message
              : '无法加载笔记模板',
          )
        }
      }
    },
    [],
  )

  const loadNotes = useCallback(
    async () => {
      const requestId = ++notesRequestId.current
      if (!knowledgeBaseId) {
        setNotes([])
        return
      }

      setLoading(true)
      setErrorMessage('')

      try {
        const result = await searchNotes(
          knowledgeBaseId,
          searchQuery,
          100,
        )

        if (requestId === notesRequestId.current) {
          setNotes(normalizeNotes(result))
        }
      } catch (error) {
        if (requestId === notesRequestId.current) {
          setErrorMessage(
            error instanceof Error
              ? error.message
              : '无法加载笔记',
          )
        }
      } finally {
        if (requestId === notesRequestId.current) {
          setLoading(false)
        }
      }
    },
    [
      knowledgeBaseId,
      searchQuery,
    ],
  )

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadKnowledgeBases()
    }, 0)

    return () => {
      window.clearTimeout(timer)
    }
  }, [loadKnowledgeBases])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadTemplates()
    }, 0)

    return () => {
      window.clearTimeout(timer)
    }
  }, [loadTemplates])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadNotes()
    }, 250)

    return () => {
      window.clearTimeout(timer)
    }
  }, [loadNotes])

  useEffect(() => {
    if (!knowledgeBaseId || !notes.some((note) =>
      note.vector_index_status === 'pending' ||
      note.vector_index_status === 'indexing'
    )) {
      return
    }

    const pendingNotes = notes.filter((note) =>
      note.vector_index_status === 'pending' ||
      note.vector_index_status === 'indexing'
    )
    const timer = window.setTimeout(async () => {
      try {
        const latestNotes = (await Promise.all(
          pendingNotes.map((note) => getNote(note.id).catch(() => null)),
        )).filter((note): note is NoteResponse => note !== null)
        const latestById = new Map(latestNotes.map((note) => [note.id, note]))
        setNotes((current) => current.map((note) => latestById.get(note.id) ?? note))
        setSelectedNote((current) => current ? latestById.get(current.id) ?? current : current)
      } catch {
        // Keep the last known state; the manual refresh remains available.
      }
    }, 3000)

    return () => window.clearTimeout(timer)
  }, [knowledgeBaseId, notes])

  useEffect(() => {
    if (!showEditor) {
      return
    }

    const timer = window.setTimeout(() => {
      if (!title.trim() && !content.trim()) {
        return
      }

      localStorage.setItem(
        noteDraftStorageKey,
        JSON.stringify({
          title,
          content,
          category: noteCategory,
          tags: tagsInput,
        } satisfies NoteDraft),
      )
      setDraftStatus('草稿已自动保存')
    }, 1000)

    return () => window.clearTimeout(timer)
  }, [showEditor, title, content, noteCategory, tagsInput, noteDraftStorageKey])

  const visibleNotes = useMemo(() => {
    if (!category) {
      return notes
    }

    return notes.filter(
      (note) =>
        getNoteCategory(note) === category,
    )
  }, [notes, category])

  const outlineItems = useMemo(
    () => extractOutline(editContent),
    [editContent],
  )

  const relatedNotes = useMemo(() => {
    if (!selectedNote) {
      return []
    }

    const selectedTags = new Set(getNoteTags(selectedNote))
    return notes
      .filter((note) => note.id !== selectedNote.id)
      .map((note) => {
        const sharedTags = getNoteTags(note).filter((tag) =>
          selectedTags.has(tag),
        ).length
        const sameCategory =
          getNoteCategory(note) !== '' &&
          getNoteCategory(note) === getNoteCategory(selectedNote)

        return {
          note,
          score: sharedTags * 2 + (sameCategory ? 1 : 0),
        }
      })
      .filter((item) => item.score > 0)
      .sort((left, right) => right.score - left.score)
      .slice(0, 4)
      .map((item) => item.note)
  }, [notes, selectedNote])

  function resetEditor() {
    setTitle('')
    setContent('')
    setNoteCategory('')
    setTagsInput('')
  }

  function openEditor() {
    const draft = readNoteDraft(noteDraftStorageKey)
    if (draft && (draft.title || draft.content)) {
      setTitle(draft.title)
      setContent(draft.content)
      setNoteCategory(draft.category)
      setTagsInput(draft.tags)
      setDraftStatus('已恢复本地草稿')
    } else {
      resetEditor()
      setDraftStatus('')
    }
    setSelectedNote(null)
    setShowEditor(true)
  }

  function closeEditor() {
    setShowEditor(false)
    resetEditor()
    setShowTemplatePicker(false)
    setEditingTemplateId(null)
  }

  function applyTemplate(template: NoteTemplate) {
    setTitle(template.title)
    setContent(template.content)
    setNoteCategory(template.category)
    setTagsInput(template.tags)
    setDraftStatus(`已应用模板：${template.name}`)
    setEditingTemplateId(null)
    setShowTemplatePicker(false)
  }

  function editTemplate(template: NoteTemplate) {
    setTitle(template.title)
    setContent(template.content)
    setNoteCategory(template.category)
    setTagsInput(template.tags)
    setEditingTemplateId(template.id)
    setShowTemplatePicker(false)
    setDraftStatus(`正在编辑模板：${template.name}`)
  }

  async function saveCurrentAsTemplate() {
    const currentTemplate = editingTemplateId
      ? templates.find((item) => item.id === editingTemplateId)
      : undefined
    const name = window.prompt(
      '输入模板名称',
      currentTemplate?.name ?? '',
    )?.trim()
    if (!name) {
      return
    }

    const templateInput = {
      name,
      title,
      content,
      category: noteCategory,
      tags: tagsInput,
    }

    try {
      const template = editingTemplateId
        ? await updateNoteTemplate(
            editingTemplateId,
            templateInput,
          )
        : await createNoteTemplate(templateInput)

      setTemplates((current) => editingTemplateId
        ? current.map((item) => item.id === template.id ? template : item)
        : [template, ...current])
      setEditingTemplateId(null)
      setDraftStatus(`模板“${name}”已保存`)
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '保存模板失败',
      )
    }
  }

  async function deleteTemplate(templateId: string) {
    const template = templates.find((item) => item.id === templateId)
    if (!template || !window.confirm(`删除模板“${template.name}”？`)) {
      return
    }

    try {
      await deleteNoteTemplate(templateId)
      setTemplates((current) =>
        current.filter((item) => item.id !== templateId),
      )
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '删除模板失败',
      )
    }
  }

  function downloadEditedNote() {
    const blob = new Blob(
      [editContent],
      { type: 'text/markdown;charset=utf-8' },
    )
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${editTitle.trim() || '未命名笔记'}.md`
    link.click()
    URL.revokeObjectURL(url)
  }

  function suggestMetadataLocallyForEdit() {
    const suggestion = suggestLocalMetadata(editTitle, editContent)
    setEditCategory(suggestion.category)
    setEditTagsInput(suggestion.tags.join(', '))
    setDraftStatus('已根据正文生成本地分类和标签')
  }

  async function handleCreateNote(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (!knowledgeBaseId) {
      setErrorMessage('默认知识库尚未准备好，请稍后重试')
      return
    }

    if (!title.trim()) {
      setErrorMessage('请输入笔记标题')
      return
    }

    const tags = tagsInput
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)

    setSaving(true)
    setErrorMessage('')

    try {
      const note = await createNote({
        knowledge_base_id: knowledgeBaseId,
        title: title.trim(),
        content,
        metadata: {
          category: noteCategory,
          tags,
        },
      })

      setNotes((current) => [
        note,
        ...current,
      ])

      localStorage.removeItem(noteDraftStorageKey)

      closeEditor()
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '创建笔记失败',
      )
    } finally {
      setSaving(false)
    }
  }

  // ✨ 新增：开始编辑笔记（填充表单）
  function startEditingNote(
    note: NoteResponse,
  ) {
    assistAbortRef.current?.abort()
    setEditTitle(note.title)
    setEditContent(note.content)
    setEditCategory(getNoteCategory(note))
    setEditTagsInput(
      getNoteTags(note).join(', '),
    )
    setTabCompletionVisible(false)
    setTabCompletionLoading(false)
    setWritingAssistOutput('')
    setWritingAssistAction(null)
    setWritingAssistError('')
    setWritingAssistLoading(false)
    setEditingNote(true)
  }

  const hasUnsavedNoteChanges = useCallback(() => {
    if (!selectedNote) return false

    const editedTags = editTagsInput
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)

    return editTitle.trim() !== selectedNote.title ||
      editContent !== selectedNote.content ||
      editCategory !== getNoteCategory(selectedNote) ||
      JSON.stringify(editedTags) !== JSON.stringify(getNoteTags(selectedNote))
  }, [editCategory, editContent, editTagsInput, editTitle, selectedNote])

  const confirmDiscardNoteChanges = useCallback(() => {
    return !editingNote || !hasUnsavedNoteChanges() ||
      window.confirm(t('notes.discardChangesConfirm'))
  }, [editingNote, hasUnsavedNoteChanges, t])

  const closeSelectedNote = useCallback(() => {
    if (detailSaving || !confirmDiscardNoteChanges()) return
    setSelectedNote(null)
    setEditingNote(false)
    const triggerId = noteDetailTriggerIdRef.current
    window.requestAnimationFrame(() => {
      if (!triggerId) return
      const trigger = Array.from(
        document.querySelectorAll<HTMLElement>('.note-card[data-note-id]'),
      ).find((card) => card.dataset.noteId === triggerId)
      trigger?.focus()
    })
  }, [confirmDiscardNoteChanges, detailSaving])

  useEffect(() => {
    closeSelectedNoteRef.current = closeSelectedNote
  }, [closeSelectedNote])

  useEffect(() => {
    if (!selectedNote) return

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        closeSelectedNoteRef.current()
        return
      }

      if (event.key !== 'Tab') return

      const dialog = document.querySelector<HTMLElement>(
        '.note-detail-backdrop [role="dialog"]',
      )
      if (!dialog) return

      const focusableElements = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.getClientRects().length > 0)
      if (focusableElements.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]
      const activeElement = document.activeElement

      if (event.shiftKey && (activeElement === firstElement || !dialog.contains(activeElement))) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && (activeElement === lastElement || !dialog.contains(activeElement))) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedNote])

  useEffect(() => {
    if (!selectedNoteId || editingNote) return

    const focusFrame = window.requestAnimationFrame(() => {
      noteDetailCloseButtonRef.current?.focus()
    })
    return () => window.cancelAnimationFrame(focusFrame)
  }, [editingNote, selectedNoteId])

  // ✨ 新增：取消编辑
  function cancelEditingNote() {
    if (detailSaving || !confirmDiscardNoteChanges()) return
    assistAbortRef.current?.abort()
    assistAbortRef.current = null
    setWritingAssistOutput('')
    setWritingAssistAction(null)
    setWritingAssistError('')
    setWritingAssistLoading(false)
    setEditingNote(false)
  }

  async function handleAutocomplete(
    context: string,
  ): Promise<string> {
    if (!context.trim()) {
      return ''
    }

    try {
      const result = await autocompleteNote(context)
      return result.completion.trim()
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : 'Tab 补全失败',
      )
      return ''
    }
  }

  function handleAutocompleteState(
    state: 'idle' | 'loading' | 'ready',
  ) {
    setTabCompletionVisible(state === 'ready')
    setTabCompletionLoading(state === 'loading')
  }

  async function runWritingAssist(
    action: WritingAssistAction,
  ) {
    const selection = richEditorRef.current?.getSelection()
    const sourceContent = selection?.text.trim() || editContent

    if (!sourceContent.trim()) {
      setWritingAssistError('请先输入一些正文内容')
      return
    }

    assistAbortRef.current?.abort()
    const controller = new AbortController()
    assistAbortRef.current = controller
    setWritingAssistAction(action)
    setWritingAssistOutput('')
    setWritingAssistError('')
    setWritingAssistLoading(true)

    try {
      let output = ''
      for await (const chunk of assistNoteStream(
        sourceContent,
        action,
        controller.signal,
      )) {
        output += chunk
        setWritingAssistOutput(output)
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }

      setWritingAssistError(
        error instanceof Error
          ? error.message
          : '写作助手失败',
      )
    } finally {
      if (assistAbortRef.current === controller) {
        assistAbortRef.current = null
      }
      setWritingAssistLoading(false)
    }
  }

  function applyWritingAssistResult() {
    const output = writingAssistOutput

    if (!output) {
      return
    }

    const selection = richEditorRef.current?.getSelection()
    if (selection?.text) {
      richEditorRef.current?.replaceSelection(output)
    } else {
      richEditorRef.current?.insertText(
        `${editContent && !editContent.endsWith('\n') ? '\n\n' : ''}${output}`,
      )
    }
  }

  // ✨ 新增：保存修改
  async function handleUpdateNote(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (!selectedNote) {
      return
    }

    if (!editTitle.trim()) {
      setErrorMessage('请输入笔记标题')
      return
    }

    const tags = editTagsInput
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)

    setDetailSaving(true)
    setErrorMessage('')

    try {
      const updated = await updateNote(
        selectedNote.id,
        {
          title: editTitle.trim(),
          content: editContent,
          metadata: {
            ...selectedNote.metadata,
            category: editCategory,
            tags,
          },
        },
      )

      setNotes((current) =>
        current.map((note) =>
          note.id === updated.id
            ? updated
            : note,
        ),
      )

      setSelectedNote(updated)
      setEditingNote(false)
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '保存笔记失败',
      )
    } finally {
      setDetailSaving(false)
    }
  }

  async function handleRetryNoteIndex(note: NoteResponse) {
    setRetryingNoteId(note.id)
    try {
      const updated = await retryNoteIndex(note.id)
      setNotes((current) => current.map((item) =>
        item.id === updated.id ? updated : item,
      ))
      setSelectedNote(updated)
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : t('notes.indexRetryFailed'),
      )
    } finally {
      setRetryingNoteId(null)
    }
  }

  // ✨ 新增：删除笔记
  async function handleDeleteSelectedNote() {
    if (!selectedNote) {
      return
    }

    const confirmed = window.confirm(
      `确定删除笔记“${selectedNote.title}”吗？`,
    )

    if (!confirmed) {
      return
    }

    setDetailSaving(true)
    setErrorMessage('')

    try {
      await deleteNote(selectedNote.id)

      setNotes((current) =>
        current.filter(
          (note) =>
            note.id !== selectedNote.id,
        ),
      )

      setSelectedNote(null)
      setEditingNote(false)
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '删除笔记失败',
      )
    } finally {
      setDetailSaving(false)
    }
  }

  if (selectedNote && editingNote) {
    return (
      <NotebookShell
        activeView="notes"
        email={email}
        onNavigate={
          onNavigate ??
          (() => undefined)
        }
        onLogout={
          onLogout ??
          (() => undefined)
        }
      >
        <main className="note-editor-page">
          <header className="note-editor-topbar">
            <button
              className="note-editor-back-button"
              type="button"
              onClick={cancelEditingNote}
              aria-label={t('notes.detail')}
              title={t('notes.detail')}
            >
              ←
            </button>

            <span className="note-editor-status">
              {t('notes.editor')}
            </span>

            <div className="note-editor-top-actions">
              <button
                className={
                  outlineVisible
                    ? 'secondary-button active'
                    : 'secondary-button'
                }
                type="button"
                onClick={() => setOutlineVisible((current) => !current)}
                disabled={detailSaving}
              >
                {t('notes.outline')}
              </button>

              <button
                className="secondary-button"
                type="button"
                onClick={downloadEditedNote}
                disabled={detailSaving}
              >
                {t('notes.export')}
              </button>

              <button
                className="secondary-button"
                type="button"
                onClick={cancelEditingNote}
                disabled={detailSaving}
              >
                {t('notes.cancel')}
              </button>

              <button
                className="primary-button"
                type="submit"
                form="standalone-note-edit-form"
                disabled={detailSaving}
              >
                {detailSaving ? t('notes.saving') : t('notes.save')}
              </button>
            </div>
          </header>

          {outlineVisible && (
            <aside className="note-outline-panel" aria-label={t('notes.outlineTitle')}>
              <div className="note-outline-heading">
                <strong>{t('notes.outlineTitle')}</strong>
                <span>{outlineItems.length} {t('notes.outlineItems')}</span>
              </div>

              {outlineItems.length === 0 ? (
                <p className="muted">{t('notes.outlineHint')}</p>
              ) : (
                <nav className="note-outline-list">
                  {outlineItems.map((item, index) => (
                    <button
                      className="note-outline-item"
                      key={`${item.text}-${index}`}
                      type="button"
                      style={{ paddingLeft: `${10 + (item.level - 1) * 14}px` }}
                      onClick={() => {
                        richEditorRef.current?.scrollToHeading(
                          item.text,
                          item.level,
                        )
                      }}
                    >
                      {item.text}
                    </button>
                  ))}
                </nav>
              )}
            </aside>
          )}

          <form
            id="standalone-note-edit-form"
            className="standalone-note-edit-form"
            onSubmit={handleUpdateNote}
          >
            <input
              className="standalone-note-title"
              value={editTitle}
              onChange={(event) =>
                setEditTitle(event.target.value)
              }
              maxLength={200}
              placeholder={t('notes.untitled')}
              autoFocus
            />

            <div className="standalone-note-meta">
              <div
                className="note-editor-category-pills"
                aria-label={t('notes.category')}
              >
                {CATEGORIES.map((item) => (
                  <button
                    className={
                      editCategory === item.value
                        ? 'note-editor-category active'
                        : 'note-editor-category'
                    }
                    key={item.value || 'all'}
                    type="button"
                    onClick={() =>
                      setEditCategory(item.value)
                    }
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              <input
                className="note-editor-tags-input"
                value={editTagsInput}
                onChange={(event) =>
                  setEditTagsInput(event.target.value)
                }
                placeholder={t('notes.tagsPlaceholder')}
                aria-label={t('notes.tags')}
              />

              <button
                className="secondary-button note-metadata-button"
                type="button"
                onClick={suggestMetadataLocallyForEdit}
              >
                {t('notes.autoMetadata')}
              </button>
            </div>

            <div className="writing-assist-toolbar" aria-label={t('notes.aiWriting')}>
              <span className="writing-assist-label">{t('notes.aiWriting')}</span>
              {([
                ['continue', t('notes.continue')],
                ['expand', t('notes.expand')],
                ['summarize', t('notes.summarize')],
                ['polish', t('notes.polish')],
              ] as const).map(([action, label]) => (
                <button
                  className={
                    writingAssistAction === action
                      ? 'writing-assist-button active'
                      : 'writing-assist-button'
                  }
                  key={action}
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => void runWritingAssist(action)}
                  disabled={writingAssistLoading}
                >
                  {label}
                </button>
              ))}

              {writingAssistLoading && (
                <button
                  className="writing-assist-button muted"
                  type="button"
                  onClick={() => assistAbortRef.current?.abort()}
                >
                  {t('notes.stop')}
                </button>
              )}

              <span
                className={
                  tabCompletionVisible
                    ? 'tab-completion-indicator active'
                    : 'tab-completion-indicator'
                }
                title={
                  tabCompletionLoading
                    ? '正在生成内联建议'
                    : tabCompletionVisible
                      ? '按 Tab 采纳，按 Esc 忽略'
                      : '输入停顿后自动生成建议'
                }
              >
                {tabCompletionLoading
                  ? '补全中...'
                  : tabCompletionVisible
                    ? 'Tab 采纳'
                    : '停顿后补全'}
              </span>
            </div>

            {(writingAssistOutput || writingAssistError) && (
              <section className="writing-assist-panel" aria-live="polite">
                <div className="writing-assist-panel-header">
                  <strong>
                    {writingAssistLoading ? t('notes.generating') : t('notes.assistResult')}
                  </strong>
                  {writingAssistOutput && !writingAssistLoading && (
                    <button
                      className="writing-assist-apply"
                      type="button"
                      onClick={applyWritingAssistResult}
                    >
                      {t('notes.insert')}
                    </button>
                  )}
                </div>
                {writingAssistError ? (
                  <p className="writing-assist-error">{writingAssistError}</p>
                ) : (
                  <p className="writing-assist-output">{writingAssistOutput}</p>
                )}
              </section>
            )}

            <Suspense
              fallback={
                <div className="rich-editor-loading">
                  {t('notes.loadingEditor')}
                </div>
              }
            >
              <RichNoteEditor
                ref={richEditorRef}
                value={editContent}
                onChange={setEditContent}
                onAutocomplete={handleAutocomplete}
                onAutocompleteState={handleAutocompleteState}
                placeholder={t('notes.writingPlaceholder')}
              />
            </Suspense>
          </form>
        </main>
      </NotebookShell>
    )
  }

  return (
    <NotebookShell
      activeView="notes"
      email={email}
      onNavigate={
        onNavigate ??
        (() => undefined)
      }
      onLogout={
        onLogout ??
        (() => undefined)
      }
    >
      <main className="notes-page">
        <header className="notebook-page-header">
          <div>
            <p className="eyebrow">
              Notebook
            </p>

            <h1>{t('notes.title')}</h1>
          </div>

          <button
            className="primary-button"
            type="button"
            onClick={openEditor}
          >
            {t('notes.new')}
          </button>
        </header>

        <section className="notebook-page-content">
          <div className="notes-toolbar">
            <span className="notes-knowledge-context">{t('notes.currentKnowledge')}</span>
            <input
              className="notes-search"
              value={searchQuery}
              onChange={(event) => {
                notesRequestId.current += 1
                setLoading(false)
                setSearchQuery(event.target.value)
              }}
              placeholder={t('notes.search')}
              aria-label={t('notes.search')}
            />
          </div>

          <div className="notes-category-row">
            {CATEGORIES.map((item) => (
              <button
                className={
                  category === item.value
                    ? 'category-pill active'
                    : 'category-pill'
                }
                type="button"
                key={item.value}
                onClick={() =>
                  setCategory(item.value)
                }
              >
                {item.label}
              </button>
            ))}
          </div>

          {errorMessage && (
            <div className="message error-message">
              {errorMessage}
            </div>
          )}

          {showEditor && (
            <section className="note-editor-panel">
              <div className="notes-section-heading">
                <div>
                  <p className="eyebrow">
                    New note
                  </p>

                    <h2>{t('notes.new')}</h2>
                </div>

                <div className="note-editor-heading-actions">
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => setShowTemplatePicker((current) => !current)}
                  >
                    {showTemplatePicker ? t('notes.closeTemplate') : t('notes.chooseTemplate')}
                  </button>

                  <button
                    className="secondary-button"
                    type="button"
                    onClick={saveCurrentAsTemplate}
                  >
                    {editingTemplateId ? t('notes.updateTemplate') : t('notes.saveTemplate')}
                  </button>

                  <button
                    className="text-button"
                    type="button"
                    onClick={closeEditor}
                  >
                    {t('notes.close')}
                  </button>
                </div>
              </div>

              {showTemplatePicker && (
                <section className="note-template-picker" aria-label={t('notes.templatePickerLabel')}>
                  <div className="note-template-picker-heading">
                    <strong>{t('notes.templateTitle')}</strong>
                    <span className="muted">{t('notes.templateHint')}</span>
                  </div>

                  {templates.length === 0 ? (
                    <p className="muted">{t('notes.noTemplates')}</p>
                  ) : (
                    <div className="note-template-list">
                      {templates.map((template) => (
                        <div className="note-template-item" key={template.id}>
                          <button
                            className="note-template-apply"
                            type="button"
                            onClick={() => applyTemplate(template)}
                          >
                            <strong>{template.name}</strong>
                            <span>{template.title || '未命名笔记'}</span>
                          </button>
                          <button
                            className="note-template-edit"
                            type="button"
                            aria-label={`编辑模板 ${template.name}`}
                            title="编辑模板"
                            onClick={() => editTemplate(template)}
                          >
                            ✎
                          </button>
                          <button
                            className="note-template-delete"
                            type="button"
                            aria-label={`删除模板 ${template.name}`}
                            title="删除模板"
                            onClick={() => deleteTemplate(template.id)}
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )}

              <form
                className="note-form"
                onSubmit={handleCreateNote}
              >
                <input
                  className="note-title-input"
                  value={title}
                  onChange={(event) =>
                    setTitle(event.target.value)
                  }
                  placeholder={t('notes.titlePlaceholder')}
                  maxLength={200}
                  autoFocus
                />

                <div className="note-meta-fields">
                  <label className="field-label">
                    {t('notes.category')}

                    <select
                      value={noteCategory}
                      onChange={(event) =>
                        setNoteCategory(
                          event.target.value,
                        )
                      }
                    >
                      <option value="">
                        {t('notes.uncategorized')}
                      </option>

                      {CATEGORIES.filter(
                        (item) => item.value,
                      ).map((item) => (
                        <option
                          key={item.value}
                          value={item.value}
                        >
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="field-label">
                    {t('notes.tags')}

                    <input
                      value={tagsInput}
                      onChange={(event) =>
                        setTagsInput(
                          event.target.value,
                        )
                      }
                      placeholder="FastAPI, RAG, notes"
                    />
                  </label>
                </div>

                <textarea
                  className="note-content-input"
                  value={content}
                  onChange={(event) =>
                    setContent(event.target.value)
                  }
                    placeholder={t('notes.contentPlaceholder')}
                  rows={14}
                />

                <div className="note-form-actions">
                  <span className="note-draft-status" aria-live="polite">
                    {draftStatus}
                  </span>

                  <button
                    className="secondary-button"
                    type="button"
                    onClick={closeEditor}
                  >
                    {t('notes.cancel')}
                  </button>

                  <button
                    className="primary-button"
                    type="submit"
                    disabled={saving}
                  >
                    {saving
                      ? t('notes.saving')
                      : t('notes.save')}
                  </button>
                </div>
              </form>
            </section>
          )}

          <div className="notes-section-heading">
            <div>
              <p className="eyebrow">
                Your notes
              </p>

              <h2>
                {t('notes.title')}{' '}
                <span className="muted">
                  ({visibleNotes.length})
                </span>
              </h2>
            </div>

            <button
              className="text-button"
              type="button"
              onClick={() => void loadNotes()}
              disabled={loading}
            >
              {loading ? t('notes.loading') : t('notes.refresh')}
            </button>
          </div>

          {visibleNotes.length === 0 ? (
            <div className="empty-state notes-empty-state">
              <strong>
                {loading
                  ? t('notes.loadingNotes')
                  : t('notes.empty')}
              </strong>

              <p>
                {t('notes.emptyHint')}
              </p>

              {!loading && (
                <button
                  className="primary-button"
                  type="button"
                  onClick={openEditor}
                >
                  {t('notes.new')}
                </button>
              )}
            </div>
          ) : (
            <div className="notes-list">
              {visibleNotes.map((note) => {
                const tags = getNoteTags(note)
                const noteCategoryValue =
                  getNoteCategory(note)
                const indexStatus = note.vector_index_status ?? 'unknown'
                const indexStatusLabel = {
                  unknown: t('notes.indexUnknown'),
                  pending: t('notes.indexPending'),
                  indexing: t('notes.indexing'),
                  ready: t('notes.indexReady'),
                  failed: t('notes.indexFailed'),
                  skipped: t('notes.indexSkipped'),
                }[indexStatus]

                return (
                  <article
                    className="note-card"
                    data-note-id={note.id}
                    key={note.id}
                    tabIndex={0}
                    role="button"
                    onClick={() => {
                      noteDetailTriggerIdRef.current = note.id
                      setSelectedNote(note)
                      setEditingNote(false) // 关闭编辑模式
                    }}
                    onKeyDown={(event) => {
                      if (
                        event.key === 'Enter' ||
                        event.key === ' '
                      ) {
                        event.preventDefault()
                        noteDetailTriggerIdRef.current = note.id
                        setSelectedNote(note)
                        setEditingNote(false)
                      }
                    }}
                  >
                    <div className="note-card-header">
                      <h3>{note.title}</h3>

                      <time className="muted">
                        {formatDate(note.updated_at, language)}
                      </time>
                    </div>

                    <p className="note-preview">
                      {getPreview(note.content) ||
                        '暂无正文内容'}
                    </p>

                    <div className={`note-index-status is-${indexStatus}`}>
                      <span aria-hidden="true" />
                      {indexStatusLabel ?? t('notes.indexUnknown')}
                    </div>

                    <div className="note-card-footer">
                      <div className="note-tags">
                        {noteCategoryValue && (
                          <span className="tag-pill">
                            {CATEGORY_LABELS[
                              noteCategoryValue
                            ] ??
                              noteCategoryValue}
                          </span>
                        )}

                        {tags.map((tag) => (
                          <span
                            className="tag-pill secondary"
                            key={tag}
                          >
                            {tag}
                          </span>
                        ))}

                        {!noteCategoryValue &&
                          tags.length === 0 && (
                            <span className="muted">
                              未分类
                            </span>
                          )}
                      </div>

                      <span className="muted">
                        {formatDate(note.created_at, language)}
                      </span>
                    </div>
                  </article>
                )
              })}
            </div>
          )}
        </section>

        {selectedNote && (
          <div
            className={
              editingNote
                ? 'note-detail-backdrop note-editor-backdrop'
                : 'note-detail-backdrop'
            }
            role="presentation"
            onClick={closeSelectedNote}
          >
            <aside
              className={
                editingNote
                  ? 'note-detail-drawer note-editor-drawer'
                  : 'note-detail-drawer'
              }
              role="dialog"
              aria-modal="true"
              aria-label={t('notes.detail')}
              tabIndex={-1}
              onClick={(event) =>
                event.stopPropagation()
              }
            >
              {editingNote ? (
                <div className="note-editor-topbar">
                  <button
                    className="note-editor-back-button"
                    type="button"
                    onClick={cancelEditingNote}
                    aria-label={t('notes.detail')}
                    title={t('notes.detail')}
                  >
                    ←
                  </button>

                  <span className="note-editor-status">
                    {t('notes.editor')}
                  </span>

                  <div className="note-editor-top-actions">
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={cancelEditingNote}
                      disabled={detailSaving}
                    >
                      {t('notes.cancel')}
                    </button>

                    <button
                      className="primary-button"
                      type="submit"
                      form="note-edit-form"
                      disabled={detailSaving}
                    >
                      {detailSaving ? t('notes.saving') : t('notes.save')}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="note-detail-header">
                  <div>
                    <p className="eyebrow">{t('notes.detail')}</p>

                    <h2>{selectedNote.title}</h2>
                  </div>

                  <button
                    ref={noteDetailCloseButtonRef}
                    className="text-button"
                    type="button"
                    onClick={closeSelectedNote}
                    aria-label={t('notes.close')}
                  >
                    {t('notes.close')}
                  </button>
                </div>
              )}

              {!editingNote && <div className="note-detail-meta">
                <span>
                  {formatDate(selectedNote.updated_at, language)}
                </span>

                <span className={`note-index-status is-${selectedNote.vector_index_status ?? 'unknown'}`}>
                  <span aria-hidden="true" />
                  {{
                    unknown: t('notes.indexUnknown'),
                    pending: t('notes.indexPending'),
                    indexing: t('notes.indexing'),
                    ready: t('notes.indexReady'),
                    failed: t('notes.indexFailed'),
                    skipped: t('notes.indexSkipped'),
                  }[selectedNote.vector_index_status ?? 'unknown'] ?? t('notes.indexUnknown')}
                </span>

                {(selectedNote.vector_index_status === 'failed' ||
                  !selectedNote.vector_index_status ||
                  selectedNote.vector_index_status === 'unknown') && (
                  <button
                    className="text-button note-index-retry"
                    type="button"
                    onClick={() => void handleRetryNoteIndex(selectedNote)}
                    disabled={retryingNoteId === selectedNote.id}
                  >
                    {retryingNoteId === selectedNote.id
                      ? t('notes.indexRetrying')
                      : selectedNote.vector_index_status === 'failed'
                        ? t('notes.retryIndex')
                        : t('notes.buildIndex')}
                  </button>
                )}

                {getNoteCategory(
                  selectedNote,
                ) && (
                  <span className="tag-pill">
                    {CATEGORY_LABELS[
                      getNoteCategory(selectedNote)
                    ] ??
                      getNoteCategory(selectedNote)}
                  </span>
                )}

                {getNoteTags(selectedNote).map(
                  (tag) => (
                    <span
                      className="tag-pill secondary"
                      key={tag}
                    >
                      {tag}
                    </span>
                  ),
                )}
              </div>}

              {/* ✨ 根据编辑状态渲染不同内容 */}
              {editingNote ? (
                <form
                  id="note-edit-form"
                  className="note-detail-editor note-editor-form"
                  onSubmit={handleUpdateNote}
                >
                  <input
                    className="note-title-input"
                    value={editTitle}
                    onChange={(event) =>
                      setEditTitle(event.target.value)
                    }
                    maxLength={200}
                    placeholder={t('notes.titlePlaceholder')}
                    autoFocus
                  />

                  <div className="note-editor-meta-row">
                    <div className="note-editor-category-pills" aria-label={t('notes.category')}>
                      {CATEGORIES.map((item) => (
                        <button
                          className={
                            editCategory === item.value
                              ? 'note-editor-category active'
                              : 'note-editor-category'
                          }
                          key={item.value || 'all'}
                          type="button"
                          onClick={() => setEditCategory(item.value)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>

                    <input
                      className="note-editor-tags-input"
                      value={editTagsInput}
                      onChange={(event) =>
                        setEditTagsInput(event.target.value)
                      }
                      placeholder={t('notes.tagsPlaceholder')}
                      aria-label={t('notes.tags')}
                    />
                  </div>

                  <Suspense
                    fallback={
                      <div className="rich-editor-loading note-detail-rich-editor-loading">
                        {t('notes.loadingEditor')}
                      </div>
                    }
                  >
                    <RichNoteEditor
                      value={editContent}
                      onChange={setEditContent}
                      onAutocomplete={handleAutocomplete}
                      onAutocompleteState={handleAutocompleteState}
                      placeholder={t('notes.richPlaceholder')}
                    />
                  </Suspense>

                  <div className="note-form-actions note-editor-bottom-actions">
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={cancelEditingNote}
                      disabled={detailSaving}
                    >
                      {t('notes.cancel')}
                    </button>

                    <button
                      className="primary-button"
                      type="submit"
                      disabled={detailSaving}
                    >
                      {detailSaving
                        ? t('notes.saving')
                        : t('notes.saveChanges')}
                    </button>
                  </div>
                </form>
              ) : (
                <>
                  <article className="note-detail-content">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                    >
                      {selectedNote.content ||
                        t('notes.noContent')}
                    </ReactMarkdown>
                  </article>

                  {relatedNotes.length > 0 && (
                    <section className="note-related-panel" aria-label={t('notes.related')}>
                      <div className="note-related-heading">
                        <strong>{t('notes.related')}</strong>
                        <span className="muted">{t('notes.relatedHint')}</span>
                      </div>
                      <div className="note-related-list">
                        {relatedNotes.map((note) => (
                          <button
                            className="note-related-item"
                            key={note.id}
                            type="button"
                            onClick={() => {
                              noteDetailTriggerIdRef.current = note.id
                              setSelectedNote(note)
                              setEditingNote(false)
                            }}
                          >
                            <strong>{note.title}</strong>
                            <span>{getPreview(note.content) || t('notes.noContent')}</span>
                          </button>
                        ))}
                      </div>
                    </section>
                  )}

                  <div className="note-detail-actions">
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation()
                        startEditingNote(selectedNote)
                      }}
                      data-testid="edit-note-button"
                    >
                      {t('notes.editor')}
                    </button>

                    <button
                      className="danger-button"
                      type="button"
                      onClick={() =>
                        void handleDeleteSelectedNote()
                      }
                      disabled={detailSaving}
                    >
                      {t('notes.delete')}
                    </button>
                  </div>
                </>
              )}
            </aside>
          </div>
        )}
      </main>
    </NotebookShell>
  )
}

export default NotesPage
