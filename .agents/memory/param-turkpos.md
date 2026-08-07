---
name: Param POS / TurkPos integration
description: Correct TurkPos SOAP endpoints/method/hash for the OnProv 3D flow, and the test-env network restriction that blocks live testing from Replit.
---

# Param POS (TurkPos) integration

The platform integrates Param POS via the TurkPos SOAP service (`turkpos.ws`). Authoritative spec: dev.param.com.tr (on-provizyon / odeme pages) + the live WSDL (`?wsdl`).

## Correct values (OnProv pre-auth 3D flow)
- **Endpoints** (choose by `param_env` setting):
  - test → `https://test-dmz.param.com.tr:4443/turkpos.ws/service_turkpos_test.asmx`
  - prod → `https://dmz.param.com.tr/turkpos.ws/service_turkpos_prod.asmx`
- **3D init method**: `TP_Islem_Odeme_OnProv_WMD` (NOT `TP_Islem_Odeme_OnProv_WKV` — that method does not exist; using it yields a "Server did not recognize SOAPAction" 500 fault). SOAPAction header must match the method.
- **Init hash** (`Islem_Hash`): `SHA2B64 = base64(sha256( CLIENT_CODE + GUID + Islem_Tutar + Toplam_Tutar + Siparis_ID + Hata_URL + Basarili_URL ))`. Amounts use Turkish decimal comma (e.g. `149,00`).
- **WMD element order** ends with `Taksit` LAST (after Data1-5).

## Two different 3D models — do not mix
- **OnProv (pre-auth) family**: `..._OnProv_WMD` (init) → `..._OnProv_Kapa` (capture). Kapa schema = `(G, GUID, Prov_ID, Prov_Tutar, Siparis_ID)`, no hash.
- **UCD family**: `TP_WMD_UCD` → `TP_WMD_Pay`, uses `UCD_MD`.
- KNOWN BUG (unfixed as of this writing): `param_pos_soap_3d_kapa` + `param_success` send `UCD_MD/Islem_ID` to the OnProv Kapa method — that's UCD-family data on an OnProv call, so capture will fail. Also `param_success` grants entitlements via the pending-record lookup even when no verified capture occurred (auth-bypass risk). Both need fixing once a responding gateway is available to test against.

## Why live testing is blocked from Replit
**Param's test backend does not respond to actual SOAP *processing* requests from the Replit network.** Symptoms: the WSDL GET loads fine and an invalid SOAPAction returns an instant 500 fault (so TLS + egress to `:4443` work), but ANY valid processing method — even a lightweight credentials-only `TP_Ozel_Oran_SK_Liste` (G+GUID, no bank) — hangs and ReadTimeouts at 45-90s. This is classic IP-whitelist / test-environment-restriction behavior on Param's side, not our code.
**How to apply:** Don't burn time chasing timeouts from the dev box. Verify Param end-to-end from the deployed server (its egress IP may be registered with Param) and/or confirm with Param that the test merchant + server IP are allowlisted. `prod` host `dmz.param.com.tr` does not even DNS-resolve from Replit dev.
