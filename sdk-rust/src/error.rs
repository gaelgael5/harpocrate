use thiserror::Error;

#[derive(Error, Debug)]
pub enum HarpocrateError {
    #[error("invalid token: {0}")]
    InvalidToken(String),

    #[error("token expired")]
    TokenExpired,

    #[error("HTTP {status}: {body}")]
    Http { status: u16, body: String },

    #[error("network error: {0}")]
    Network(String),

    #[error("decryption failed: {0}")]
    Decryption(String),

    #[error("serde error: {0}")]
    Serde(#[from] serde_json::Error),

    #[error("secret not found: {0}")]
    SecretNotFound(String),

    #[error("placeholder not populated: {0}")]
    PlaceholderNotPopulated(String),
}

impl From<reqwest::Error> for HarpocrateError {
    fn from(err: reqwest::Error) -> Self {
        HarpocrateError::Network(err.to_string())
    }
}
