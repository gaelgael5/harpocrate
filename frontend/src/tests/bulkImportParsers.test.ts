import { describe, it, expect } from 'vitest'
import { parseBulkImport } from '@/lib/bulkImportParsers'

describe('parseBulkImport — empty input', () => {
  it('rejects empty string', () => {
    const r = parseBulkImport('')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('empty')
  })

  it('rejects whitespace-only', () => {
    const r = parseBulkImport('   \n\t  ')
    expect(r.ok).toBe(false)
  })
})

describe('parseBulkImport — .env format', () => {
  it('parses simple KEY=VALUE lines', () => {
    const r = parseBulkImport('FOO=bar\nBAZ=qux')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.format).toBe('env')
      expect(r.secrets).toEqual([
        { name: 'FOO', value: 'bar' },
        { name: 'BAZ', value: 'qux' },
      ])
    }
  })

  it('ignores empty lines and comments', () => {
    const r = parseBulkImport(`
# This is a comment
FOO=bar

# Another
BAZ=qux
`)
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.secrets).toHaveLength(2)
  })

  it('strips wrapping double quotes', () => {
    const r = parseBulkImport('FOO="hello world"')
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.secrets[0]?.value).toBe('hello world')
  })

  it('strips wrapping single quotes', () => {
    const r = parseBulkImport("FOO='hello'")
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.secrets[0]?.value).toBe('hello')
  })

  it('preserves = signs inside the value', () => {
    const r = parseBulkImport('URL=postgres://user:p@host/db?ssl=true')
    expect(r.ok).toBe(true)
    if (r.ok)
      expect(r.secrets[0]?.value).toBe('postgres://user:p@host/db?ssl=true')
  })

  it('rejects line without =', () => {
    const r = parseBulkImport('FOO_BAR_NO_EQ')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('line 1')
  })
})

describe('parseBulkImport — JSON flat format (B)', () => {
  it('parses simple flat object', () => {
    const r = parseBulkImport('{"FOO": "bar", "BAZ": "qux"}')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.format).toBe('json-flat')
      expect(r.secrets).toEqual([
        { name: 'FOO', value: 'bar' },
        { name: 'BAZ', value: 'qux' },
      ])
    }
  })

  it('rejects non-string values in flat JSON', () => {
    const r = parseBulkImport('{"FOO": 42}')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('must be a string')
  })

  it('rejects empty object', () => {
    const r = parseBulkImport('{}')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('empty')
  })

  it('rejects array (must be object)', () => {
    const r = parseBulkImport('[]')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('object')
  })

  it('rejects invalid JSON', () => {
    const r = parseBulkImport('{not valid json')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('invalid JSON')
  })
})

describe('parseBulkImport — Harpocrate format (D)', () => {
  it('parses Harpocrate envelope', () => {
    const r = parseBulkImport(JSON.stringify({
      format: 'harpocrate-bulk-import',
      version: 1,
      secrets: [
        { name: 'A', value: '1' },
        { name: 'B', value: '2' },
      ],
    }))
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.format).toBe('harpocrate')
      expect(r.secrets).toHaveLength(2)
    }
  })

  it('rejects Harpocrate format without secrets array', () => {
    const r = parseBulkImport('{"format":"harpocrate-bulk-import"}')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('secrets')
  })

  it('rejects Harpocrate item missing name or value', () => {
    const r = parseBulkImport(JSON.stringify({
      format: 'harpocrate-bulk-import',
      secrets: [{ name: 'X' }],
    }))
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('name')
  })
})

describe('parseBulkImport — auto-detection priority', () => {
  it('treats {"format":"...other..."} as flat JSON, not Harpocrate', () => {
    // Si la clé `format` n'est pas la valeur sentinelle, c'est traité comme
    // flat JSON (et la valeur "other" est juste considérée comme une string).
    const r = parseBulkImport('{"format":"other","KEY":"value"}')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.format).toBe('json-flat')
      // 2 secrets : "format" et "KEY"
      expect(r.secrets).toHaveLength(2)
    }
  })
})
