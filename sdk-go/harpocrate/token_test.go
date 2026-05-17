package harpocrate

import "testing"

func TestParseTokenRejectsInvalidPrefix(t *testing.T) {
	_, err := ParseToken("foo_bar")
	if err == nil {
		t.Fatalf("expected error, got nil")
	}
	if _, ok := err.(*InvalidTokenError); !ok {
		t.Errorf("expected InvalidTokenError, got %T", err)
	}
}

func TestParseTokenRejectsTooShort(t *testing.T) {
	_, err := ParseToken("hrpv_1_short")
	if err == nil {
		t.Fatalf("expected error, got nil")
	}
	if _, ok := err.(*InvalidTokenError); !ok {
		t.Errorf("expected InvalidTokenError, got %T", err)
	}
}
