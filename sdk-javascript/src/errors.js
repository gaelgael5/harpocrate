/**
 * Erreurs typées exposées par le SDK Harpocrate.
 */

export class HarpocrateError extends Error {
  constructor(message) {
    super(message);
    this.name = 'HarpocrateError';
  }
}

export class InvalidTokenError extends HarpocrateError {
  constructor(reason, message) {
    super(message ?? `invalid token: ${reason}`);
    this.name = 'InvalidTokenError';
    this.reason = reason;
  }
}

export class TokenExpiredError extends HarpocrateError {
  constructor() {
    super('token expired');
    this.name = 'TokenExpiredError';
  }
}

export class SecretNotFoundError extends HarpocrateError {
  constructor(name) {
    super(`secret not found: ${name}`);
    this.name = 'SecretNotFoundError';
    this.secretName = name;
  }
}

export class VaultHttpError extends HarpocrateError {
  constructor(status, body) {
    super(`vault http error ${status}: ${body}`);
    this.name = 'VaultHttpError';
    this.status = status;
    this.body = body;
  }
}

export class VaultDecryptionError extends HarpocrateError {
  constructor(reason) {
    super(`decryption failed: ${reason}`);
    this.name = 'VaultDecryptionError';
    this.reason = reason;
  }
}
