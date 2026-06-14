---
name: lost-card-replacement
description: "Handles replacement requests for lost or stolen cards."
allowed-tools:
  - fetch_customer_profile
  - freeze_card
  - assess_shipping_risk
  - order_replacement
  - send_notification
---
# Lost/Stolen Debit Card Replacement Skill

This skill allows the agent to process a debit card replacement. It retrieves account details, freezes the old card, evaluates shipping risk, prompts for manager approval when express shipping is chosen, and dispatches the new card.

## Preconditions
- The customer account must be active.

## Steps
1. Fetch customer details and card list using `fetch_customer_profile`.
2. Perform fraud analysis. If suspicious, freeze the card.
3. Determine shipping risk. Express shipping requires manager approval.
4. Place the order using `order_replacement`.
5. Notify the customer using `send_notification`.
