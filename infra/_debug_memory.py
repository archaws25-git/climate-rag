"""Debug: check what get_last_k_turns returns after saving."""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

os.environ["CLIMATE_RAG_MEMORY_ID"] = "ClimateRAGMemory-tdkH1G52GJ"
os.environ["AWS_PROFILE"] = "AdministratorAccess-357312912554"
os.environ["AWS_REGION"] = "us-east-1"

from tools.memory_tool import save_turn, _get_session

actor_id = f"debug-{uuid.uuid4().hex[:6]}"
session_id = f"debug-{uuid.uuid4().hex[:6]}"

# Save 2 turns
print("Saving turns...")
save_turn(actor_id, session_id, "user", "What is the temp in Atlanta?")
save_turn(actor_id, session_id, "assistant", "Atlanta averages 17C.")

# Wait for consistency
print("Waiting 10 seconds for consistency...")
time.sleep(10)

# Retrieve
print("Retrieving turns...")
session = _get_session(actor_id, session_id)
turns = session.get_last_k_turns(k=5)

print(f"Got {len(turns)} turns")
for i, turn in enumerate(turns):
    print(f"  Turn {i}: type={type(turn).__name__}")
    print(f"    dir: {[a for a in dir(turn) if not a.startswith('_')]}")
    if hasattr(turn, "text"):
        print(f"    .text = {turn.text!r}")
    if hasattr(turn, "role"):
        print(f"    .role = {turn.role!r}")
    if hasattr(turn, "content"):
        print(f"    .content = {turn.content!r}")
    if isinstance(turn, dict):
        print(f"    keys = {turn.keys()}")
    print(f"    str = {str(turn)[:150]}")
