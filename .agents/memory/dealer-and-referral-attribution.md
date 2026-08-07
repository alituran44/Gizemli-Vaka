---
name: Dealer/referral commission attribution
description: How QR/coupon referral commission is attributed for both non-team and team purchases, and the single-use session rule.
---

# Referral attribution (dealer "bayilik" + partner "ortak")

Two independent referral systems credit commission on a sale: partner (coupon `?ref=` codes) and dealer (cafe QR at `/b/<token>`). Both must be handled at EVERY payment success path or commission silently goes untracked.

## Two distinct code paths per purchase type
- **Non-team purchases**: referral lives in the session (`applied_discount` for partner, `dealer_ref` for dealer). Attribution runs inside `record_partner_sale` / `record_dealer_sale`, called per-item in cart loops at each success handler.
- **Team purchases**: referral is captured onto the `TeamPurchase` row at creation time (`partner_code`, `dealer_code`, `dealer_qr_template_id`), because the session may not survive the multi-step 3D-secure team flow. Attribution runs in `record_partner_sale_for_team` / `record_dealer_sale_for_team`, which read the code off the row and then null it out to prevent double-credit.

**Why:** team and non-team have separate success handlers (team_purchase_complete, iyzico/param/paynkolay team branches vs. cart/case success). A new referral system added only to `record_*_sale` will miss all team sales. Always add the team equivalent alongside every `record_partner_sale_for_team` call site.

## Single-use rule (avoid over-crediting)
Referral is consumed once per purchase, not once per session:
- Non-team: `session.pop('dealer_ref', None)` sits next to every `session.pop('applied_discount', None)` in the 6 purchase-completion handlers — but NOT in the `remove_discount` route (that pop is a coupon removal, not a sale).
- Team: the code is nulled on the row after attribution.

**Why:** leaving `dealer_ref` in the session over-credits the dealer on unrelated later purchases in the same browser session.

## How to apply
When adding/auditing any commission/referral feature: enumerate ALL payment success handlers (grep the existing `record_partner_sale*` call sites — they are the canonical list) and mirror the new attribution at each, for both non-team and team, plus the single-use cleanup.
