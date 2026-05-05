export class HarpocrateError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'HarpocrateError'
  }
}

export class InvalidTokenError extends HarpocrateError {
  constructor(public readonly code: string, message?: string) {
    super(message ?? code)
    this.name = 'InvalidTokenError'
  }
}

export class TokenExpiredError extends HarpocrateError {
  constructor() {
    super('Token has expired')
    this.name = 'TokenExpiredError'
  }
}

export class VaultHttpError extends HarpocrateError {
  constructor(public readonly status: number, public readonly body: string) {
    super(`HTTP ${status}: ${body}`)
    this.name = 'VaultHttpError'
  }
}

export class VaultDecryptionError extends HarpocrateError {
  constructor(message: string) {
    super(message)
    this.name = 'VaultDecryptionError'
  }
}

export class SecretNotFoundError extends HarpocrateError {
  constructor(name: string) {
    super(`Secret '${name}' not found`)
    this.name = 'SecretNotFoundError'
  }
}
