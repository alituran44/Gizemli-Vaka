---
name: PaynKolay callback verification
description: How to verify PaynKolay 3D success callbacks server-side (hashDataV2 formula) and the fail-open pitfalls to avoid
---

# PaynKolay 3D callback verification

Rule: never grant access from `/payment/paynkolay/success` without (a) verifying the callback signature and (b) finding the exact matching pending payment record.

**Callback response hash formula (official docs):**
`hashDataV2 = base64(sha512("MERCHANT_NO|REFERENCE_CODE|AUTH_CODE|RESPONSE_CODE|USE_3D|RND|INSTALLMENT|AUTHORIZATION_AMOUNT|CURRENCY_CODE|merchantSecretKey"))`
- Compare with `hmac.compare_digest`.
- Success also requires `RESPONSE_CODE == '2'` and non-empty, non-'0' `AUTH_CODE`.
- The callback `RND` is PaynKolay-generated (different from the request `rnd`).
- Callback may use `CLIENT_REFERENCE_CODE` instead of `clientRefCode`.

**Why:** clientRefCode is not secret (visible in browser/referrer); without signature verification anyone could forge the success URL for free access. Session-based fallback unlock branches are fail-open (replays pass signature check after pending record is deleted) — they were removed; missing pending record must be a hard stop.

**How to apply:** any new payment provider callback must verify provider-signed data server-side before unlocking; iyzico (API detail check) and Param (SOAP Kapa) are the in-repo reference implementations.
