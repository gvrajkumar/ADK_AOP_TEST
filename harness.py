import os
import yaml
import logging
import asyncio
import time
from typing import Dict, Any, List, Optional

from models import AgenticSOP, SOPStep
from tools_registry import CAPABILITY_BINDINGS, MOCK_ACCOUNTS

# Import Google ADK classes
from google.adk import Agent, Runner, Context
from google.adk.models import BaseLlm, LLMRegistry
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

logger = logging.getLogger("Harness")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# =====================================================================
# High-Fidelity Mock LLM for local/offline testing with ADK
# =====================================================================
class MockLlm(BaseLlm):
    model: str = "gpt-4o"

    @classmethod
    def supported_models(cls) -> List[str]:
        # Bind to standard models if we want mock fallback
        return [r"gpt-4o", r"gpt-.*"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ):
        """Simulates the LLM reasoning process and tool execution logic with metadata."""
        customer_id = "cust-987"
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text:
                        if "cust-123" in part.text:
                            customer_id = "cust-123"
                        elif "cust-987" in part.text:
                            customer_id = "cust-987"

        # Check if agent has tools and if a tool call was already made
        has_tools = False
        if llm_request.config and llm_request.config.tools:
            has_tools = True

        last_is_tool_response = False
        if llm_request.contents:
            last_content = llm_request.contents[-1]
            if last_content.role == "tool" or (
                last_content.parts and any(p.function_response for p in last_content.parts)
            ):
                last_is_tool_response = True

        if has_tools and not last_is_tool_response:
            # Step 1: LLM decides to invoke the tool to get transaction history
            logger.info("[MockLLM] Agent is planning. Decided to call tool: get_transaction_history")
            tool_call_part = types.Part.from_function_call(
                name="get_transaction_history",
                args={"customer_id": customer_id}
            )
            # Stamp a call ID as required by ADK/OpenAI schema
            tool_call_part.function_call.id = "call_fraud_analysis_001"
            
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[tool_call_part]
                ),
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=150,
                    candidates_token_count=20,
                    total_token_count=170
                ),
                partial=False
            )
        else:
            # Step 2: Tool response is present, LLM analyzes and makes the final decision
            logger.info("[MockLLM] Agent is analyzing tool results to make decision...")
            tool_output = ""
            for content in reversed(llm_request.contents):
                if content.parts:
                    for part in content.parts:
                        if part.function_response:
                            tool_output = str(part.function_response.response)
                            break
                if tool_output:
                    break

            if "cust-123" in tool_output or customer_id == "cust-123":
                text_response = (
                    "Analysis completed: true\n"
                    "Decision: HIGH RISK. Suspicious ATM withdrawal in Paris ($500) followed by a large online "
                    "transfer ($10,000) to a foreign account within minutes. Fraud is highly probable."
                )
            else:
                text_response = (
                    "Analysis completed: true\n"
                    "Decision: LOW RISK. Recent transaction history shows normal grocery, coffee, and utility "
                    "purchases in New York, matching the customer's profile. No fraud detected."
                )

            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=text_response)]
                ),
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=380,
                    candidates_token_count=100,
                    total_token_count=480
                ),
                partial=False
            )

# Auto-register MockLlm if no real OpenAI API Key is present
openai_key = os.environ.get("OPENAI_API_KEY", "")
if not openai_key or openai_key.lower() in ("mock", "dummy", "none"):
    logger.info("No active OPENAI_API_KEY found. Registering high-fidelity MockLlm provider for 'gpt-4o'.")
    LLMRegistry.register(MockLlm)
else:
    logger.info("Active OPENAI_API_KEY found. Using real OpenAI API endpoint.")


# =====================================================================
# ADK Agent Custom Tool definition for transaction checks
# =====================================================================
def get_transaction_history(customer_id: str) -> str:
    """Retrieves recent transactions for a customer to analyze for fraud.

    Args:
        customer_id: The ID of the customer to query.
    """
    logger.info(f"[Agent Tool] Fetching transaction history for customer: {customer_id}")
    if customer_id == "cust-123":
        return (
            "Transactions for customer cust-123:\n"
            "- 2026-06-12 10:15:20: ATM withdrawal $500 in Paris, France (Suspicious: Location mismatch)\n"
            "- 2026-06-12 10:18:45: Online transfer $10,000 to foreign account (Suspicious: Large transfer)\n"
            "- 2026-06-13 09:30:00: Balance inquiry from IP 203.0.113.50 (Location: Russia)"
        )
    else:
        return (
            "Transactions for customer cust-987:\n"
            "- 2026-06-11 12:30:15: Grocery store $84.20 in New York, NY\n"
            "- 2026-06-12 08:45:00: Coffee shop $4.50 in New York, NY\n"
            "- 2026-06-13 11:20:00: Utility payment $120.00 in New York, NY"
        )


# =====================================================================
# Stateful Harness Orchestrator
# =====================================================================
class HarnessAgent:
    def __init__(self, workflow_path: str):
        self.workflow_path = workflow_path
        self.sop: Optional[AgenticSOP] = None
        self.context: Dict[str, Any] = {}
        self.executed_steps: List[str] = [] # Tracks executed steps for rollback

    def load_workflow(self):
        """Loads and validates the executable YAML workflow."""
        logger.info(f"Loading Agentic SOP from: {self.workflow_path}")
        with open(self.workflow_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.sop = AgenticSOP.model_validate(data)
        logger.info(f"Successfully loaded SOP: '{self.sop.title}' (Version {self.sop.version})")

    def _resolve_template(self, template_str: str) -> str:
        """Resolves template values like '{{customer_id}}' from execution context."""
        if not isinstance(template_str, str):
            return template_str
        
        # Simple regex replace for {{variable_name}}
        import re
        def replacer(match):
            var_name = match.group(1).strip()
            val = self.context.get(var_name, match.group(0))
            return str(val)
            
        return re.sub(r"\{\{(.*?)\}\}", replacer, template_str)

    def _evaluate_expression(self, expr_str: str) -> bool:
        """Evaluates precondition or success criteria against execution context."""
        # Replace YAML syntax 'true'/'false' with Python 'True'/'False'
        eval_locals = {
            **self.context,
            "true": True,
            "false": False,
            "True": True,
            "False": False
        }
        try:
            # Evaluate safely with restricted builtins
            return eval(expr_str, {"__builtins__": None}, eval_locals)
        except Exception as e:
            logger.error(f"Error evaluating expression '{expr_str}': {e}")
            return False

    async def execute_step(self, step: SOPStep) -> bool:
        """Executes a single step depending on its action type and measures latency."""
        logger.info(f"\n--- [STEP RUN] Executing Step: {step.id} (Action: {step.action}) ---")
        
        # 1. Resolve inputs
        resolved_inputs = {}
        if step.inputs:
            for k, v in step.inputs.items():
                resolved_inputs[k] = self._resolve_template(v)

        # 2. Dispatch by action with latency tracking
        start_step_time = time.time()
        
        if step.action == "execute":
            success = await self._run_execute_action(step, resolved_inputs)
        elif step.action == "diagnose":
            success = await self._run_diagnose_action(step)
        elif step.action == "decision":
            success = await self._run_decision_action(step, resolved_inputs)
        else:
            logger.error(f"Unknown action type: '{step.action}' in step '{step.id}'")
            success = False

        duration_ms = int((time.time() - start_step_time) * 1000)
        
        # Log step-level latency telemetry
        logger.info(f"[TELEMETRY] Step '{step.id}' executed in {duration_ms}ms")
        if step.telemetry and step.telemetry.alert_on_latency_ms:
            if duration_ms > step.telemetry.alert_on_latency_ms:
                logger.warning(
                    f"⚠️  [TELEMETRY ALERT] Step '{step.id}' latency {duration_ms}ms "
                    f"exceeded configured threshold limit of {step.telemetry.alert_on_latency_ms}ms!"
                )
                
        return success

    async def _run_execute_action(self, step: SOPStep, resolved_inputs: Dict[str, Any]) -> bool:
        """Binds and runs an abstract capability using the LOB Registry."""
        capability = step.capability
        if capability not in CAPABILITY_BINDINGS:
            logger.error(f"Missing LOB capability binding for '{capability}'")
            return False
            
        binding = CAPABILITY_BINDINGS[capability]
        concrete_func = binding["function"]
        param_mapping = binding.get("param_mapping", {})
        default_args = binding.get("default_args", {})

        # Map abstract inputs -> concrete function arguments
        mapped_args = {}
        for abstract_key, val in resolved_inputs.items():
            concrete_key = param_mapping.get(abstract_key, abstract_key)
            mapped_args[concrete_key] = val
            
        # Add default arguments if not overridden
        for def_k, def_v in default_args.items():
            if def_k not in mapped_args:
                mapped_args[def_k] = def_v

        logger.info(f"[Harness Binder] Mapping capability '{capability}' -> LOB Function '{concrete_func.__name__}'")
        logger.info(f"[Harness Binder] Arguments: {mapped_args}")
        
        try:
            # Execute LOB concrete function
            result = await concrete_func(**mapped_args)
            logger.info(f"[LOB Output] Result: {result}")
            
            # Check for technical timeout/errors returned in payload
            if "error" in result:
                logger.error(f"[LOB Error] Concrete function reported error: {result['error']}")
                return False

            # Update context with output values
            self.context.update(result)
            
            # Evaluate success criteria
            if step.success_criteria:
                success = self._evaluate_expression(step.success_criteria)
                logger.info(f"[Harness Evaluator] Criteria '{step.success_criteria}' satisfied: {success}")
                if success:
                    self.executed_steps.append(step.id)
                return success
                
            self.executed_steps.append(step.id)
            return True
            
        except Exception as e:
            logger.exception(f"Execution failed for capability '{capability}': {e}")
            return False

    async def _run_diagnose_action(self, step: SOPStep) -> bool:
        """Instantiates and executes a Google ADK Agent to evaluate card activity."""
        logger.info(f"[ADK Harness] Spawning ADK Agent for diagnose capability '{step.capability}'")
        
        # Instantiate the ADK Agent
        model_name = os.environ.get("OPENAI_MODEL", "gpt-5.5")
        agent = Agent(
            name="FraudDetectorAgent",
            model=model_name,
            instruction=(
                f"You are a specialized bank fraud analysis agent. {step.instruction} "
                "You must use the get_transaction_history tool to examine transactions before making a decision. "
                "Always conclude your final analysis with 'Analysis completed: true' so the harness can parse it."
            ),
            tools=[get_transaction_history]
        )
        
        # Initialize Runner with In-Memory session
        session_service = InMemorySessionService()
        runner = Runner(agent=agent, session_service=session_service, app_name="FraudAnalysisApp", auto_create_session=True)
        
        user_prompt = (
            f"Inspect recent transactions for customer '{self.context.get('customer_id')}' "
            "and determine if there is suspicious or fraudulent activity."
        )
        
        logger.info(f"[ADK Harness] Running agent with prompt: '{user_prompt}'")
        
        agent_response_text = ""
        prompt_tokens = 0
        comp_tokens = 0
        total_tokens = 0
        
        try:
            async for event in runner.run_async(
                user_id="harness_user",
                session_id="session_diag_1",
                new_message=types.Content(parts=[types.Part.from_text(text=user_prompt)])
            ):
                # Monitor token usage metadata from runner stream
                if event.usage_metadata:
                    prompt_tokens = event.usage_metadata.prompt_token_count or prompt_tokens
                    comp_tokens = event.usage_metadata.candidates_token_count or comp_tokens
                    total_tokens = event.usage_metadata.total_token_count or total_tokens
                    
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            # Stream outputs to the logs
                            print(part.text, end="", flush=True)
                            agent_response_text += part.text
            print() # Carriage return
            
            # Print token usage telemetry
            if step.telemetry and step.telemetry.monitor_token_usage:
                logger.info(f"[TELEMETRY] LLM Token Usage: prompt={prompt_tokens}, completion={comp_tokens}, total={total_tokens}")
                # Calculate estimated API costs (approx. $15/M input, $60/M output tokens)
                step_cost = (prompt_tokens * 0.000015) + (comp_tokens * 0.000060)
                logger.info(f"[TELEMETRY] Estimated Step LLM Cost: ${step_cost:.6f} USD")
                self.context["accumulated_cost_usd"] = self.context.get("accumulated_cost_usd", 0.0) + step_cost

            # Print explainability audit log if required by SOP
            if step.explainability and step.explainability.required:
                justification = agent_response_text.replace("Analysis completed: true", "").strip()
                logger.info(f"\n🔍 [EXPLAINABILITY AUDIT TRAIL] Mode: {step.explainability.mode}")
                logger.info(f"🔍 [EXPLAINABILITY AUDIT TRAIL] Justification: {justification}\n")
                if step.explainability.target_field:
                    self.context[step.explainability.target_field] = justification
            
            # Update context with results parsed from the LLM outputs
            if "analysis completed: true" in agent_response_text.lower():
                self.context["analysis_completed"] = True
            else:
                self.context["analysis_completed"] = False
                
            if "suspicious activity detected" in agent_response_text.lower() or "high risk" in agent_response_text.lower():
                logger.warning("[ADK Harness] Agent flagged transactions as HIGH RISK / SUSPICIOUS!")
                self.context["fraud_detected"] = True
            else:
                logger.info("[ADK Harness] Agent flagged transactions as LOW RISK.")
                self.context["fraud_detected"] = False
                
            # Verify success criteria
            if step.success_criteria:
                success = self._evaluate_expression(step.success_criteria)
                logger.info(f"[Harness Evaluator] Criteria '{step.success_criteria}' satisfied: {success}")
                if success:
                    self.executed_steps.append(step.id)
                return success
                
            self.executed_steps.append(step.id)
            return True
            
        except Exception as e:
            logger.exception(f"ADK Agent execution failed: {e}")
            return False

    async def _run_decision_action(self, step: SOPStep, resolved_inputs: Dict[str, Any]) -> bool:
        """Evaluates risk profiles and prompts for Human-In-The-Loop approvals if required."""
        capability = step.capability
        if capability not in CAPABILITY_BINDINGS:
            logger.error(f"Missing LOB capability binding for '{capability}'")
            return False
            
        binding = CAPABILITY_BINDINGS[capability]
        concrete_func = binding["function"]
        param_mapping = binding.get("param_mapping", {})
        
        mapped_args = {}
        for abstract_key, val in resolved_inputs.items():
            concrete_key = param_mapping.get(abstract_key, abstract_key)
            mapped_args[concrete_key] = val

        logger.info(f"[Harness Binder] Running risk assessment capability '{capability}' -> '{concrete_func.__name__}'")
        
        try:
            # Run the LOB risk assessment tool
            result = await concrete_func(**mapped_args)
            logger.info(f"[LOB Output] Result: {result}")
            self.context.update(result)
            
            # Check Human-In-The-Loop condition
            if step.human_approval == "required_if_express":
                shipping_speed = self.context.get("shipping_speed", "").upper()
                requires_approval = result.get("requires_approval", False)
                
                if shipping_speed.startswith("EXPRESS") and requires_approval:
                    logger.warning("\n🚧 [HUMAN APPROVAL GATE TRIGGERED] 🚧")
                    logger.warning(f"Customer profile indicates elevated delivery risk.")
                    logger.warning(f"Reason: {result.get('reason', 'High shipping risk score')}")
                    
                    # Display explainability context to human reviewer if available
                    if "fraud_justification" in self.context:
                        logger.info(f"💡 [Review Context] Fraud Agent Reasoning Path: {self.context['fraud_justification']}")
                    
                    # Simulated prompt
                    choice = input("👉 Enter 'y' to grant Manager Approval, or 'n' to reject: ").strip().lower()
                    if choice != 'y':
                        logger.error("[Harness Gate] Human approval was REJECTED by the manager.")
                        return False
                    logger.info("[Harness Gate] Human approval GRANTED. Continuing execution.")
                    self.context["manager_approved"] = True
                else:
                    logger.info("[Harness Gate] Express shipping risk checks passed automatically.")
            
            self.executed_steps.append(step.id)
            return True
            
        except Exception as e:
            logger.exception(f"Decision step failed: {e}")
            return False

    async def execute_rollback(self):
        """Runs rollback steps in reverse order to restore bank state."""
        logger.warning("\n🔄 [ROLLBACK TRIGGERED] Executing recovery workflow...")
        if not self.sop or not self.sop.rollback:
            logger.info("No rollback steps defined.")
            return

        for rollback_step in self.sop.rollback:
            logger.info(f"[Rollback Step] Executing: {rollback_step.id} (Capability: {rollback_step.capability})")
            
            resolved_inputs = {}
            if rollback_step.inputs:
                for k, v in rollback_step.inputs.items():
                    resolved_inputs[k] = self._resolve_template(v)
                    
            capability = rollback_step.capability
            if capability not in CAPABILITY_BINDINGS:
                logger.error(f"Missing LOB capability binding for rollback: '{capability}'")
                continue
                
            binding = CAPABILITY_BINDINGS[capability]
            concrete_func = binding["function"]
            param_mapping = binding.get("param_mapping", {})
            
            mapped_args = {}
            for abstract_key, val in resolved_inputs.items():
                concrete_key = param_mapping.get(abstract_key, abstract_key)
                mapped_args[concrete_key] = val
                
            try:
                result = await concrete_func(**mapped_args)
                logger.info(f"[Rollback Output] Result: {result}")
            except Exception as e:
                logger.error(f"Rollback step '{rollback_step.id}' failed: {e}")
        logger.info("Rollback operations completed.")

    async def run(self, initial_inputs: Dict[str, Any]) -> bool:
        """Main orchestrator running the step graph."""
        self.context = dict(initial_inputs)
        self.context["accumulated_cost_usd"] = 0.0
        self.executed_steps = []
        
        self.load_workflow()
        
        # Enforce global budget settings if configured
        budget_limit = 0.50
        if self.sop.global_governance:
            budget_limit = self.sop.global_governance.max_workflow_cost_usd
            logger.info(f"[Harness Governance] Telemetry Profile: {self.sop.global_governance.telemetry_profile}")
            logger.info(f"[Harness Governance] Max Budget limit set to: ${budget_limit:.2f} USD")

        # Run steps in sequence
        for step in self.sop.steps:
            # Enforce budget guardrails before executing each step
            current_cost = self.context.get("accumulated_cost_usd", 0.0)
            if current_cost > budget_limit:
                logger.error(
                    f"❌  [GOVERNANCE BREACH] Workflow aborted! Accumulated cost ${current_cost:.5f} USD "
                    f"exceeds global budget limit threshold of ${budget_limit:.2f} USD!"
                )
                return False

            # Preconditions check if we just fetched customer profile
            if step.id == "step_fraud_check":
                # Ensure preconditions are met before doing fraud analysis
                logger.info("\n--- [PRECONDITION CHECK] ---")
                for pre in self.sop.preconditions:
                    satisfied = self._evaluate_expression(pre)
                    logger.info(f"Checking precondition '{pre}': {satisfied}")
                    if not satisfied:
                        logger.error(f"Precondition failed: '{pre}'. Stopping workflow.")
                        return False

            success = await self.execute_step(step)
            
            if not success:
                logger.error(f"\n❌ Step '{step.id}' failed!")
                
                # Check failure route
                if step.on_failure == "goto step_rollback":
                    await self.execute_rollback()
                    return False
                elif step.on_failure == "goto step_escalate":
                    logger.critical(f"Workflow halted. Escalating to LOB engineering team support.")
                    return False
                elif step.on_failure == "goto step_log_warning":
                    logger.warning(f"Non-critical step '{step.id}' failed. Logging warning and continuing.")
                    continue
                else:
                    logger.error("No valid error recovery route specified. Halting.")
                    return False
                    
        logger.info("\n🏆 [WORKFLOW COMPLETE] Card replacement workflow executed successfully.")
        return True
