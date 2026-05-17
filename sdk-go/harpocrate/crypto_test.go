package harpocrate

import (
	"bytes"
	"testing"
)

func TestAESGCMRoundTrip(t *testing.T) {
	key := bytes.Repeat([]byte{42}, 32)
	plain := []byte("hello vault")
	blob, err := AESGCMEncrypt(plain, key)
	if err != nil {
		t.Fatalf("encrypt: %v", err)
	}
	got, err := AESGCMDecrypt(blob, key)
	if err != nil {
		t.Fatalf("decrypt: %v", err)
	}
	if !bytes.Equal(got, plain) {
		t.Errorf("round-trip mismatch: got %q, want %q", got, plain)
	}
}

func TestAESGCMWrongKeyFails(t *testing.T) {
	blob, err := AESGCMEncrypt([]byte("x"), bytes.Repeat([]byte{1}, 32))
	if err != nil {
		t.Fatalf("encrypt: %v", err)
	}
	_, err = AESGCMDecrypt(blob, bytes.Repeat([]byte{2}, 32))
	if err == nil {
		t.Errorf("expected error with wrong key, got nil")
	}
	if _, ok := err.(*VaultDecryptionError); !ok {
		t.Errorf("expected VaultDecryptionError, got %T", err)
	}
}

func TestAESGCMRejectsShortKey(t *testing.T) {
	_, err := AESGCMEncrypt([]byte("x"), bytes.Repeat([]byte{0}, 16))
	if err == nil {
		t.Errorf("expected error with 16-byte key, got nil")
	}
}

func TestAESGCMRejectsShortBlob(t *testing.T) {
	_, err := AESGCMDecrypt(bytes.Repeat([]byte{0}, 5), bytes.Repeat([]byte{0}, 32))
	if err == nil {
		t.Errorf("expected error with 5-byte blob, got nil")
	}
}
