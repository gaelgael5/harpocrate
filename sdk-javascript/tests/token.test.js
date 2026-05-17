import { describe, it, expect } from 'vitest';

import { InvalidTokenError } from '../src/errors.js';
import { parseToken } from '../src/token.js';

describe('parseToken', () => {
  it('rejects invalid prefix', () => {
    expect(() => parseToken('foo_bar')).toThrow(InvalidTokenError);
  });

  it('rejects too short token', () => {
    expect(() => parseToken('hrpv_1_short')).toThrow(InvalidTokenError);
  });

  it('rejects non-string input', () => {
    expect(() => parseToken(undefined)).toThrow(InvalidTokenError);
  });
});
