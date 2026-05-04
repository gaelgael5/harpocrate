import Editor from '@monaco-editor/react'
import { useComputedColorScheme } from '@mantine/core'

export function JsonEditorMonaco({
  value,
  onChange,
  readOnly = false,
  height = '300px',
}: {
  value: string
  onChange?: (v: string) => void
  readOnly?: boolean
  height?: string
}) {
  const colorScheme = useComputedColorScheme('light', { getInitialValueInEffect: true })

  return (
    <Editor
      height={height}
      language="json"
      theme={colorScheme === 'dark' ? 'vs-dark' : 'light'}
      value={value}
      onChange={(v) => onChange?.(v ?? '')}
      options={{
        readOnly,
        minimap: { enabled: false },
        formatOnPaste: true,
        scrollBeyondLastLine: false,
        tabSize: 2,
        lineNumbers: 'on',
        wordWrap: 'on',
      }}
    />
  )
}
