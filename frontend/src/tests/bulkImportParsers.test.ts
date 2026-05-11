import { describe, it, expect } from 'vitest'
import { parseBulkImport, normalizeKey } from '@/lib/bulkImportParsers'

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

  it('rejects line without separator (no = and no :)', () => {
    const r = parseBulkImport('FOO_BAR_NO_SEP')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('line 1')
  })

  it('accepts colon separator with spaces around', () => {
    const r = parseBulkImport(
      'github token llm : FAKE_TOKEN_FOR_TEST_ONLY_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    )
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.secrets[0]?.name).toBe('github_token_llm')
      expect(r.secrets[0]?.value).toBe(
        'FAKE_TOKEN_FOR_TEST_ONLY_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      )
    }
  })

  it('= takes priority over : (preserves URL with colon in value)', () => {
    const r = parseBulkImport('URL=postgres://user:p@host/db')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.secrets[0]?.name).toBe('URL')
      expect(r.secrets[0]?.value).toBe('postgres://user:p@host/db')
    }
  })

  it('normalizes key with weird characters', () => {
    const r = parseBulkImport('API key (prod)=value123')
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.secrets[0]?.name).toBe('API_key_prod')
  })

  it('rejects line where key is only whitespace/punctuation', () => {
    const r = parseBulkImport('@@@: value')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('empty key after normalization')
  })

  it('mix of = and : lines', () => {
    const r = parseBulkImport(`
FOO=bar
my key : my value
URL=https://x.com:443
`)
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.secrets).toHaveLength(3)
      expect(r.secrets[0]).toEqual({ name: 'FOO', value: 'bar' })
      expect(r.secrets[1]).toEqual({ name: 'my_key', value: 'my value' })
      expect(r.secrets[2]).toEqual({ name: 'URL', value: 'https://x.com:443' })
    }
  })
})

describe('normalizeKey', () => {
  it('replaces spaces with _', () => {
    expect(normalizeKey('github token llm')).toBe('github_token_llm')
  })
  it('collapses consecutive _', () => {
    expect(normalizeKey('foo  bar___baz')).toBe('foo_bar_baz')
  })
  it('trims leading/trailing _', () => {
    expect(normalizeKey('  __key__  ')).toBe('key')
  })
  it('preserves dashes and existing underscores', () => {
    expect(normalizeKey('my-key_v2')).toBe('my-key_v2')
  })
  it('strips non-ASCII / emoji', () => {
    expect(normalizeKey('🔑 secret')).toBe('secret')
  })
  it('returns empty for input with only special chars', () => {
    expect(normalizeKey('@@@!!!')).toBe('')
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
