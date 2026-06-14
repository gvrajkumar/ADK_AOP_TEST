import logging

logger = logging.getLogger("LOB")

# Mock Database / State representing bank systems
MOCK_ACCOUNTS = {
    "cust-987": {
        "name": "Jane Doe",
        "account_status": "ACTIVE",
        "credit_score": 750,
        "active_cards": ["card-1111"],
        "cards_status": {"card-1111": "ACTIVE"},
        "orders": []
    },
    "cust-123": {
        "name": "John Smith",
        "account_status": "ACTIVE",
        "credit_score": 580, # Low credit score -> triggers express shipping high risk
        "active_cards": ["card-2222"],
        "cards_status": {"card-2222": "ACTIVE"},
        "orders": []
    }
}

# Concrete LOB Technical Functions (with arbitrary names and parameter schemas)

async def lob_fetch_customer_details(customer_uuid: str) -> dict:
    """Technical LOB function to retrieve customer profile and card status from mainframe DB."""
    logger.info(f"[LOB API] Fetching details for customer UUID: {customer_uuid}")
    if customer_uuid in MOCK_ACCOUNTS:
        acct = MOCK_ACCOUNTS[customer_uuid]
        return {
            "customer_found": True,
            "account_status": acct["account_status"],
            "credit_score": acct["credit_score"],
            "active_card_id": acct["active_cards"][0] if acct["active_cards"] else None,
            "cards": acct["active_cards"]
        }
    return {"customer_found": False}

async def lob_debit_card_freeze(card_num: str, reason_code: str = "PRECAUTIONARY") -> dict:
    """Technical LOB function to freeze a debit card in the card management platform."""
    logger.info(f"[LOB API] Freezing card {card_num}. Reason: {reason_code}")
    for acct in MOCK_ACCOUNTS.values():
        if card_num in acct["cards_status"]:
            acct["cards_status"][card_num] = "FROZEN"
            return {"card_id": card_num, "card_status": "FROZEN", "frozen_at_epoch": 1781292039}
    return {"error": "Card not found"}

async def lob_unfreeze_card_v2(card_identifier: str) -> dict:
    """Technical LOB function to unfreeze/restore a card's status."""
    logger.info(f"[LOB API] Restoring card {card_identifier} back to ACTIVE")
    for acct in MOCK_ACCOUNTS.values():
        if card_identifier in acct["cards_status"]:
            acct["cards_status"][card_identifier] = "ACTIVE"
            return {"card_id": card_identifier, "card_status": "ACTIVE", "restored": True}
    return {"error": "Card not found"}

async def lob_assess_shipping_risk(user_uuid: str, speed_tier: str) -> dict:
    """Technical LOB function checking if card replacement delivery requires override approval."""
    logger.info(f"[LOB API] Assessing shipping risk for user UUID: {user_uuid}, Speed: {speed_tier}")
    if user_uuid not in MOCK_ACCOUNTS:
        return {"error": "Customer not found"}
    
    credit_score = MOCK_ACCOUNTS[user_uuid]["credit_score"]
    
    # Logic: Express shipping for low credit score (risk) requires manual approval
    if speed_tier.upper().startswith("EXPRESS"):
        if credit_score < 600:
            return {"risk_score": 85, "requires_approval": True, "reason": "Low credit score for Express delivery"}
        return {"risk_score": 20, "requires_approval": False}
    return {"risk_score": 5, "requires_approval": False}

async def lob_order_replacement_service(client_id: str, speed_tier: str) -> dict:
    """Technical LOB function ordering a replacement card. Can be configured to simulate failures."""
    logger.info(f"[LOB API] Dispatching replacement card order for client {client_id} (speed: {speed_tier})")
    
    # For testing failure and rollback, simulate mainframe timeout if customer is 'cust-123' and express shipping
    # (or we can just hardcode a flag for the simulation in main.py)
    if client_id == "cust-123" and speed_tier.upper() == "EXPRESS_FAIL":
        logger.error("[LOB API] ERROR: Mainframe Connection Timeout during order placement!")
        return {"error": "MAINFRAME_TIMEOUT", "order_status": "FAILED"}
        
    if client_id in MOCK_ACCOUNTS:
        new_card = "card-new-9999"
        MOCK_ACCOUNTS[client_id]["orders"].append(new_card)
        return {"order_status": "DISPATCHED", "card_id": new_card, "tracking_num": "TRK-882937"}
    return {"error": "Client not found"}

async def lob_send_email_notification(client_id: str, body_content: str) -> dict:
    """Technical LOB function to send customer alert messages."""
    logger.info(f"[LOB API] Sending notification to customer {client_id}: '{body_content}'")
    return {"notification_sent": True, "delivery_channel": "EMAIL"}


# LOB Binding Registry: Maps Abstract Capabilities (KM SOP) -> Concrete LOB Functions
# Supports parameter mapping (abstract -> technical) and default values
CAPABILITY_BINDINGS = {
    "fetch_customer_profile": {
        "function": lob_fetch_customer_details,
        "param_mapping": {"id": "customer_uuid"}
    },
    "freeze_card": {
        "function": lob_debit_card_freeze,
        "param_mapping": {"card_id": "card_num"},
        "default_args": {"reason_code": "LOST_STOLEN_REPORT"}
    },
    "unfreeze_card": {
        "function": lob_unfreeze_card_v2,
        "param_mapping": {"card_id": "card_identifier"}
    },
    "assess_shipping_risk": {
        "function": lob_assess_shipping_risk,
        "param_mapping": {"id": "user_uuid", "speed": "speed_tier"}
    },
    "order_replacement": {
        "function": lob_order_replacement_service,
        "param_mapping": {"id": "client_id", "speed": "speed_tier"}
    },
    "send_notification": {
        "function": lob_send_email_notification,
        "param_mapping": {"id": "client_id", "msg": "body_content"}
    }
}
