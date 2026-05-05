using Xunit;

namespace Harpocrate.Sdk.Tests;

public class AesGcmCryptoTests
{
    [Fact]
    public void Encrypt_then_Decrypt_round_trips()
    {
        var key = new byte[32];
        for (var i = 0; i < 32; i++) key[i] = (byte)i;
        var plain = System.Text.Encoding.UTF8.GetBytes("hello vault");

        var blob = AesGcmCrypto.Encrypt(plain, key);
        var decrypted = AesGcmCrypto.Decrypt(blob, key);

        Assert.Equal(plain, decrypted);
    }

    [Fact]
    public void Decrypt_with_wrong_key_throws()
    {
        var blob = AesGcmCrypto.Encrypt([0x01], new byte[32]);
        var wrongKey = new byte[32];
        wrongKey[0] = 1;
        Assert.Throws<VaultDecryptionException>(() => AesGcmCrypto.Decrypt(blob, wrongKey));
    }

    [Fact]
    public void Rejects_short_key()
    {
        Assert.Throws<VaultDecryptionException>(() =>
            AesGcmCrypto.Encrypt([0x01], new byte[16]));
    }

    [Fact]
    public void Rejects_short_blob()
    {
        Assert.Throws<VaultDecryptionException>(() =>
            AesGcmCrypto.Decrypt(new byte[5], new byte[32]));
    }

    [Fact]
    public void Blob_format_is_nonce_ciphertext_tag()
    {
        var blob = AesGcmCrypto.Encrypt([0xAA], new byte[32]);
        // 12 nonce + 1 ciphertext + 16 tag = 29
        Assert.Equal(29, blob.Length);
    }
}
