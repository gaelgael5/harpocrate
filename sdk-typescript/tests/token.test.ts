import { describe, expect, it } from 'vitest'

import { InvalidTokenError } from '../src/errors.js'
import { parseToken } from '../src/token.js'

describe('parseToken', () => {
  it('rejects invalid prefix', () => {
    expect(() => parseToken('foo_bar')).toThrowError(InvalidTokenError)
  })

  it('rejects too short', () => {
    expect(() => parseToken('hrpv_1_short')).toThrowError(InvalidTokenError)
  })

  it('rejects empty', () => {
    expect(() => parseToken('')).toThrowError(InvalidTokenError)
  })
})
