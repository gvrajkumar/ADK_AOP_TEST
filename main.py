from dotenv import load_dotenv
load_dotenv()

import openai.resources.chat.completions
original_create = openai.resources.chat.completions.AsyncCompletions.create

async def patched_create(self, *args, **kwargs):
    if "max_tokens" in kwargs:
        model = kwargs.get("model", "")
        if "gpt-5.5" in model or model.startswith("o1") or model.startswith("o3"):
            # Map max_tokens to max_completion_tokens for newer/reasoning models
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
    return await original_create(self, *args, **kwargs)

openai.resources.chat.completions.AsyncCompletions.create = patched_create

import os
import asyncio
import logging
from sop_store import SOPStore
from harness import HarnessAgent
from tools_registry import CAPABILITY_BINDINGS, MOCK_ACCOUNTS

# Configure logging to focus on harness execution steps rather than debug noise
logging.getLogger("LOB").setLevel(logging.INFO)
logging.getLogger("Harness").setLevel(logging.INFO)

async def test_sop_search():
    print("=====================================================================")
    print("🔍 TEST 1: KNOWLEDGE MANAGEMENT SOP SEARCH")
    print("=====================================================================")
    store = SOPStore(".")
    
    # Simulate an agent searching for lost card procedures
    query = "replace lost card"
    # Agent declares the capabilities/tools it supports
    agent_capabilities = [
        "fetch_customer_profile",
        "freeze_card",
        "assess_shipping_risk",
        "order_replacement",
        "send_notification",
        "unfreeze_card"
    ]
    
    print(f"Agent Search Query: '{query}'")
    print(f"Agent Registered Capabilities: {agent_capabilities}")
    
    matches = store.search(query, agent_capabilities)
    
    if matches:
        print(f"\nMatch found! Successfully retrieved {len(matches)} matching SOP(s):")
        for match in matches:
            print(f" - [{match['name']}] (Score: {match['search_score']})")
            print(f"   Description: {match['description']}")
            print(f"   Workflow path: {match['workflow_path']}")
        return matches[0]["workflow_path"]
    else:
        print("❌ No matching SOP found.")
        return None

async def test_scenario_jane_doe(workflow_path: str):
    print("\n=====================================================================")
    print("👤 TEST 2: SCENARIO 1 - JANE DOE (LOW RISK CUSTOMER)")
    print("=====================================================================")
    # Jane Doe (cust-987) has 750 credit score -> low risk, express shipping shouldn't trigger human gate
    initial_inputs = {
        "customer_id": "cust-987",
        "shipping_speed": "express"
    }
    
    # Restore MOCK_ACCOUNTS to starting state
    MOCK_ACCOUNTS["cust-987"]["cards_status"]["card-1111"] = "ACTIVE"
    MOCK_ACCOUNTS["cust-987"]["orders"] = []

    harness = HarnessAgent(workflow_path)
    success = await harness.run(initial_inputs)
    
    if success:
        print("\n✅ Scenario 1 (Jane Doe) completed successfully as expected.")
        print(f"Database State: Jane Doe active orders: {MOCK_ACCOUNTS['cust-987']['orders']}")
        print(f"Database State: Jane's card card-1111 status: {MOCK_ACCOUNTS['cust-987']['cards_status']['card-1111']}")
    else:
        print("\n❌ Scenario 1 (Jane Doe) failed unexpectedly.")

async def test_scenario_john_smith(workflow_path: str):
    print("\n=====================================================================")
    print("👤 TEST 3: SCENARIO 2 - JOHN SMITH (HIGH RISK + MAINFRAME FAIL + ROLLBACK)")
    print("=====================================================================")
    # John Smith (cust-123) has 580 credit score -> high risk.
    # Express shipping will trigger human approval gate.
    # We pass 'express_fail' as shipping speed to simulate mainframe failure on card order.
    initial_inputs = {
        "customer_id": "cust-123",
        "shipping_speed": "express_fail"
    }
    
    # Restore MOCK_ACCOUNTS to starting state
    MOCK_ACCOUNTS["cust-123"]["cards_status"]["card-2222"] = "ACTIVE"
    MOCK_ACCOUNTS["cust-123"]["orders"] = []

    harness = HarnessAgent(workflow_path)
    success = await harness.run(initial_inputs)
    
    # Expecting failure and rollback
    if not success:
        print("\n✅ Scenario 2 (John Smith) failed and rolled back as expected.")
        print(f"Database State: John's card card-2222 status: {MOCK_ACCOUNTS['cust-123']['cards_status']['card-2222']} (Unfrozen back to ACTIVE)")
        print(f"Database State: John Smith active orders: {MOCK_ACCOUNTS['cust-123']['orders']} (Empty due to roll back)")
    else:
        print("\n❌ Scenario 2 (John Smith) executed without failure unexpectedly.")

async def test_decoupled_api_migration(workflow_path: str):
    print("\n=====================================================================")
    print("🔄 TEST 4: DECOUPLED LOB MIGRATION (KM SOP REMAINS UNCHANGED)")
    print("=====================================================================")
    # We will simulate a technical LOB API upgrade.
    # We define a new concrete function representing the v3 card freeze endpoint:
    
    async def migrated_debit_card_freeze_v3(technical_card_no: str, code: str) -> dict:
        print(f"\n[MIGRATED LOB API v3] Executing upgraded freeze service...")
        print(f"[MIGRATED LOB API v3] Parameters received: card_no={technical_card_no}, reason_code={code}")
        # Mark card as frozen in database
        for acct in MOCK_ACCOUNTS.values():
            if technical_card_no in acct["cards_status"]:
                acct["cards_status"][technical_card_no] = "FROZEN"
                return {
                    "card_status": "FROZEN", 
                    "v3_migration_applied": True,
                    "service_version": "v3.0.4"
                }
        return {"error": "Card not found"}

    # Register the new migrated function under the abstract capability
    # Map the abstract input 'card_id' -> new parameter name 'technical_card_no'
    # Map default 'reason_code' -> 'code'
    CAPABILITY_BINDINGS["freeze_card"] = {
        "function": migrated_debit_card_freeze_v3,
        "param_mapping": {"card_id": "technical_card_no"},
        "default_args": {"code": "STOLEN_REPORTED_V3"}
    }
    
    print("⚙️  Simulating LOB Backend Upgrade: Upgraded debit_card_freeze to version v3.")
    print("⚙️  Parameter 'card_num' changed to 'technical_card_no'.")
    print("⚙️  Updated CAPABILITY_BINDINGS in tools_registry.py (KM YAML file left 100% UNCHANGED).")
    
    # Run card replacement for Jane Doe again to verify the migrated function is called
    initial_inputs = {
        "customer_id": "cust-987",
        "shipping_speed": "express"
    }
    
    # Restore MOCK_ACCOUNTS to starting state
    MOCK_ACCOUNTS["cust-987"]["cards_status"]["card-1111"] = "ACTIVE"
    MOCK_ACCOUNTS["cust-987"]["orders"] = []

    harness = HarnessAgent(workflow_path)
    success = await harness.run(initial_inputs)
    
    if success and harness.context.get("v3_migration_applied"):
        print("\n✅ Decoupled LOB Migration Verification SUCCESSFUL!")
        print("KM SOP executed using the upgraded v3 API without any YAML changes.")
    else:
        print("\n❌ Decoupled LOB Migration Verification FAILED.")

async def main():
    print("=====================================================================")
    print("🚀 STARTING AGENT HARNESS DEMO USING GOOGLE ADK 2.x")
    print("=====================================================================")
    
    workflow_path = await test_sop_search()
    if not workflow_path:
        print("Halting: No executable workflow found.")
        return

    # Scenario 1: Jane Doe
    await test_scenario_jane_doe(workflow_path)
    
    # Scenario 2: John Smith
    await test_scenario_john_smith(workflow_path)
    
    # Scenario 3: Decoupled API Migration
    await test_decoupled_api_migration(workflow_path)

if __name__ == "__main__":
    asyncio.run(main())
