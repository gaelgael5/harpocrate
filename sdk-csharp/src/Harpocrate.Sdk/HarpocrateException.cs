namespace Harpocrate.Sdk;

/// <summary>Exception de base du SDK Harpocrate.</summary>
public class HarpocrateException : Exception
{
    public HarpocrateException(string message) : base(message) { }
    public HarpocrateException(string message, Exception inner) : base(message, inner) { }
}

/// <summary>Token hrpv_* malformé ou non reconnu.</summary>
public class InvalidTokenException(string code, string? message = null)
    : HarpocrateException(message ?? code)
{
    public string Code { get; } = code;
}

/// <summary>Le token hrpv_* est expiré.</summary>
public class TokenExpiredException() : HarpocrateException("Token has expired") { }

/// <summary>Erreur HTTP retournée par Harpocrate.</summary>
public class VaultHttpException(int statusCode, string body)
    : HarpocrateException($"HTTP {statusCode}: {body}")
{
    public int StatusCode { get; } = statusCode;
    public string Body { get; } = body;
}

/// <summary>Échec du déchiffrement AES-GCM (tag invalide ou clé incorrecte).</summary>
public class VaultDecryptionException(string message) : HarpocrateException(message) { }

/// <summary>Le secret demandé est introuvable.</summary>
public class SecretNotFoundException(string name)
    : HarpocrateException($"Secret '{name}' not found") { }
