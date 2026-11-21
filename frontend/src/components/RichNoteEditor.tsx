import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react'

import {
  EditorContent,
  useEditor,
} from '@tiptap/react'

import { Extension, type Editor } from '@tiptap/core'
import { Plugin, PluginKey, type Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Link from '@tiptap/extension-link'
import { Table } from '@tiptap/extension-table'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import TableRow from '@tiptap/extension-table-row'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'
import Underline from '@tiptap/extension-underline'
import { useLanguage } from '../i18n'

import { marked } from 'marked'
import TurndownService from 'turndown'

const turndown = new TurndownService({
  bulletListMarker: '-',
  codeBlockStyle: 'fenced',
  emDelimiter: '*',
  headingStyle: 'atx',
  strongDelimiter: '**',
})

type InlineCompletion = { text: string; position: number }

const inlineCompletionKey = new PluginKey<InlineCompletion>(
  'inlineAiCompletion',
)

const InlineCompletionExtension = Extension.create({
  name: 'inlineAiCompletion',
  addProseMirrorPlugins() {
    return [new Plugin<InlineCompletion>({
      key: inlineCompletionKey,
      state: {
        init: () => ({ text: '', position: 0 }),
        apply(transaction, current) {
          const next = transaction.getMeta(inlineCompletionKey) as
            | InlineCompletion
            | undefined
          if (next) return next
          if (transaction.docChanged || transaction.selectionSet) {
            return { text: '', position: 0 }
          }
          return current
        },
      },
      props: {
        decorations(state) {
          const suggestion = inlineCompletionKey.getState(state)
          if (!suggestion?.text) return null
          return DecorationSet.create(state.doc, [
            Decoration.widget(suggestion.position, () => {
              const span = document.createElement('span')
              span.className = 'inline-ai-completion-suggestion'
              span.textContent = suggestion.text
              span.setAttribute('aria-hidden', 'true')
              return span
            }, {
              key: `ai-completion-${suggestion.position}-${suggestion.text}`,
              side: 1,
            }),
          ])
        },
      },
    })]
  },
})

turndown.addRule('taskListItem', {
  filter: (node) =>
    node.nodeName === 'LI' &&
    (node as HTMLElement).getAttribute('data-type') === 'taskItem',
  replacement: (content, node) => {
    const element = node as HTMLElement
    const checked = element.getAttribute('data-checked') === 'true'
    return `- [${checked ? 'x' : ' '}] ${content.trim()}\n`
  },
})

function markdownToHtml(markdown: string) {
  return marked.parse(markdown || '', { async: false }) as string
}

function markdownFromEditor(editor: Editor) {
  return turndown.turndown(editor.getHTML()).trim()
}

type ToolbarButtonProps = {
  active?: boolean
  label: string
  onClick: () => void
  title: string
}

function ToolbarButton({
  active,
  label,
  onClick,
  title,
}: ToolbarButtonProps) {
  return (
    <button
      className={active ? 'rich-editor-tool active' : 'rich-editor-tool'}
      type="button"
      title={title}
      aria-label={title}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      {label}
    </button>
  )
}

function EditorToolbar({ editor }: { editor: Editor | null }) {
  const { t } = useLanguage()
  if (!editor) {
    return null
  }

  const heading = [1, 2, 3].find((level) =>
    editor.isActive('heading', { level }),
  )

  return (
    <div className="rich-editor-toolbar" aria-label={t('notes.editorToolbar')}>
      <ToolbarButton
        active={editor.isActive('bold')}
        label="B"
        title={t('notes.rich.bold')}
        onClick={() => editor.chain().focus().toggleBold().run()}
      />
      <ToolbarButton
        active={editor.isActive('italic')}
        label="I"
        title={t('notes.rich.italic')}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      />
      <ToolbarButton
        active={editor.isActive('underline')}
        label="U"
        title={t('notes.rich.underline')}
        onClick={() => editor.chain().focus().toggleUnderline().run()}
      />
      <ToolbarButton
        active={editor.isActive('strike')}
        label="S"
        title={t('notes.rich.strike')}
        onClick={() => editor.chain().focus().toggleStrike().run()}
      />

      <span className="rich-editor-divider" />

      <select
        className="rich-editor-select"
        aria-label={t('notes.rich.headingLevel')}
        title={t('notes.rich.headingLevel')}
        value={heading ?? 0}
        onChange={(event) => {
          const level = Number(event.target.value)
          if (level === 0) {
            editor.chain().focus().setParagraph().run()
          } else {
            editor.chain().focus().toggleHeading({ level: level as 1 | 2 | 3 }).run()
          }
        }}
      >
        <option value={0}>{t('notes.rich.paragraph')}</option>
        <option value={1}>{t('notes.rich.heading1')}</option>
        <option value={2}>{t('notes.rich.heading2')}</option>
        <option value={3}>{t('notes.rich.heading3')}</option>
      </select>

      <span className="rich-editor-divider" />

      <ToolbarButton
        active={editor.isActive('bulletList')}
        label="•"
        title={t('notes.rich.bulletList')}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      />
      <ToolbarButton
        active={editor.isActive('orderedList')}
        label="1."
        title={t('notes.rich.orderedList')}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      />
      <ToolbarButton
        active={editor.isActive('taskList')}
        label="☑"
        title={t('notes.rich.taskList')}
        onClick={() => editor.chain().focus().toggleTaskList().run()}
      />
      <ToolbarButton
        active={editor.isActive('blockquote')}
        label="❝"
        title={t('notes.rich.blockquote')}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
      />
      <ToolbarButton
        active={editor.isActive('codeBlock')}
        label="</>"
        title={t('notes.rich.codeBlock')}
        onClick={() => editor.chain().focus().toggleCodeBlock().run()}
      />

      <span className="rich-editor-divider" />

      <ToolbarButton
        label="表"
        title={t('notes.rich.insertTable')}
        onClick={() => editor.chain().focus().insertTable({
          rows: 3,
          cols: 3,
          withHeaderRow: true,
        }).run()}
      />
      <ToolbarButton
        label="链"
        title={t('notes.rich.insertLink')}
        onClick={() => {
          const url = window.prompt(t('notes.rich.linkPrompt'))
          if (url?.trim()) {
            editor.chain().focus().setLink({ href: url.trim() }).run()
          }
        }}
      />
      <ToolbarButton
        label="—"
        title={t('notes.rich.horizontalRule')}
        onClick={() => editor.chain().focus().setHorizontalRule().run()}
      />

      <span className="rich-editor-divider" />

      <ToolbarButton
        label="↶"
        title={t('notes.rich.undo')}
        onClick={() => editor.chain().focus().undo().run()}
      />
      <ToolbarButton
        label="↷"
        title={t('notes.rich.redo')}
        onClick={() => editor.chain().focus().redo().run()}
      />
    </div>
  )
}

export type RichNoteEditorHandle = {
  focus: () => void
  getSelection: () => { from: number; text: string; to: number }
  insertText: (value: string) => void
  replaceSelection: (value: string) => void
  scrollToHeading: (text: string, level: number) => void
}

type RichNoteEditorProps = {
  onAutocomplete?: (context: string) => Promise<string>
  onAutocompleteState?: (state: 'idle' | 'loading' | 'ready') => void
  onChange: (value: string) => void
  placeholder?: string
  value: string
}

const RichNoteEditor = forwardRef<
  RichNoteEditorHandle,
  RichNoteEditorProps
>(function RichNoteEditor({
  onAutocomplete,
  onAutocompleteState,
  onChange,
  placeholder = '开始写作... ',
  value,
}, ref) {
  const onChangeRef = useRef(onChange)
  const onAutocompleteRef = useRef(onAutocomplete)
  const onAutocompleteStateRef = useRef(onAutocompleteState)
  const syncingRef = useRef(false)

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    onAutocompleteRef.current = onAutocomplete
    onAutocompleteStateRef.current = onAutocompleteState
  }, [onAutocomplete, onAutocompleteState])

  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({ link: false, underline: false }),
      Placeholder.configure({ placeholder }),
      Link.configure({ openOnClick: false, autolink: true }),
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      TaskList,
      TaskItem.configure({ nested: true }),
      Underline,
      InlineCompletionExtension,
    ],
    content: markdownToHtml(value),
    editorProps: {
      attributes: {
        // Keep the component-specific hook and the Tiptap hook so the editor
        // receives the same layout and typography rules as its content nodes.
        class: 'rich-editor-content tiptap',
      },
      handleKeyDown: (view, event) => {
        const suggestion = inlineCompletionKey.getState(view.state)
        if (event.key === 'Escape' && suggestion?.text) {
          event.preventDefault()
          view.dispatch(view.state.tr.setMeta(inlineCompletionKey, {
            text: '',
            position: 0,
          }))
          onAutocompleteStateRef.current?.('idle')
          return true
        }

        if (event.key !== 'Tab' || !suggestion?.text) {
          return false
        }

        event.preventDefault()
        const { from, to } = view.state.selection
        if (from !== to || from !== suggestion.position) return true
        view.dispatch(view.state.tr.setMeta(inlineCompletionKey, {
          text: '',
          position: 0,
        }))
        editor?.chain().focus().insertContentAt(from, suggestion.text).run()
        onAutocompleteStateRef.current?.('idle')

        return true
      },
    },
    onUpdate: ({ editor: updatedEditor }) => {
      if (!syncingRef.current) {
        const markdown = markdownFromEditor(updatedEditor)
        onChangeRef.current(markdown)
      }
    },
  })

  useEffect(() => {
    if (!editor || editor.isDestroyed || !editor.schema) {
      return
    }

    const currentMarkdown = markdownFromEditor(editor)
    if (currentMarkdown === value.trim()) {
      return
    }

    syncingRef.current = true
    editor.commands.setContent(markdownToHtml(value), {
      emitUpdate: false,
    })
    syncingRef.current = false
  }, [editor, value])

  useEffect(() => {
    if (!editor) return

    let timer: ReturnType<typeof setTimeout> | undefined
    let requestId = 0

    const clearSuggestion = (dispatchClear = false) => {
      requestId += 1
      if (timer) clearTimeout(timer)
      timer = undefined
      if (dispatchClear && inlineCompletionKey.getState(editor.state)?.text) {
        editor.view.dispatch(editor.state.tr.setMeta(inlineCompletionKey, {
          text: '',
          position: 0,
        }))
      }
      onAutocompleteStateRef.current?.('idle')
    }

    const scheduleCompletion = () => {
      clearSuggestion()
      if (!editor.isFocused) return

      const { from, to } = editor.state.selection
      if (from !== to) return
      const context = editor.state.doc.textBetween(
        Math.max(1, from - 2000),
        from,
        '\n',
      )
      if (!context.trim()) return

      const currentRequestId = requestId
      timer = setTimeout(async () => {
        if (currentRequestId !== requestId) return
        onAutocompleteStateRef.current?.('loading')
        try {
          const completion = (
            await onAutocompleteRef.current?.(context) ?? ''
          ).trim()
          const selection = editor.state.selection
          if (
            currentRequestId !== requestId ||
            !editor.isFocused ||
            selection.from !== from ||
            selection.to !== to ||
            !completion
          ) {
            onAutocompleteStateRef.current?.('idle')
            return
          }

          editor.view.dispatch(editor.state.tr.setMeta(inlineCompletionKey, {
            text: completion,
            position: from,
          }))
          onAutocompleteStateRef.current?.('ready')
        } catch {
          onAutocompleteStateRef.current?.('idle')
        }
      }, 700)
    }

    const handleTransaction = ({ transaction }: { transaction: Transaction }) => {
      if (transaction.docChanged) {
        scheduleCompletion()
      } else if (transaction.selectionSet) {
        clearSuggestion()
      }
    }
    const handleFocus = () => scheduleCompletion()
    const handleBlur = () => clearSuggestion(true)

    editor.on('transaction', handleTransaction)
    editor.on('focus', handleFocus)
    editor.on('blur', handleBlur)
    return () => {
      editor.off('transaction', handleTransaction)
      editor.off('focus', handleFocus)
      editor.off('blur', handleBlur)
      clearSuggestion(true)
    }
  }, [editor])

  useImperativeHandle(ref, () => ({
    focus: () => editor?.chain().focus().run(),
    getSelection: () => {
      if (!editor) {
        return { from: 0, text: '', to: 0 }
      }

      const { from, to } = editor.state.selection
      return {
        from,
        text: editor.state.doc.textBetween(from, to, '\n'),
        to,
      }
    },
    insertText: (text) => {
      editor?.chain().focus().insertContent(text).run()
    },
    replaceSelection: (text) => {
      editor?.chain().focus().insertContent(text).run()
    },
    scrollToHeading: (text, level) => {
      if (!editor) {
        return
      }

      const normalized = text.trim().toLowerCase()
      editor.state.doc.descendants((node, position) => {
        if (
          node.type.name === 'heading' &&
          node.attrs.level === level &&
          node.textContent.trim().toLowerCase() === normalized
        ) {
          const element = editor.view.nodeDOM(position)
          if (element instanceof HTMLElement) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }
          editor.commands.setTextSelection({
            from: position + 1,
            to: position + 1,
          })
          editor.commands.focus()
          return false
        }
        return true
      })
    },
  }), [editor])

  return (
    <div className="rich-editor-shell">
      <EditorToolbar editor={editor} />
      <div className="rich-editor-body">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
})

export default RichNoteEditor
