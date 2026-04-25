"""Setup AgentCore Memory for ClimateRAG."""

import json
import sys

from bedrock_agentcore_starter_toolkit.operations.memory.manager import MemoryManager
from bedrock_agentcore_starter_toolkit.operations.memory.models.strategies import SemanticStrategy

REGION = "us-east-1"
MEMORY_NAME = "ClimateRAGMemory"


def main():
    mgr = MemoryManager(region_name=REGION)

    print(f"Creating AgentCore Memory: {MEMORY_NAME}...")
    memory = mgr.get_or_create_memory(
        name=MEMORY_NAME,
        description="Climate research memory — stores researcher context and findings",
        strategies=[
            SemanticStrategy(
                name="climateSemanticMemory",
                namespace_templates=["/strategies/{memoryStrategyId}/actors/{actorId}/"],
            )
        ],
    )

    memory_id = memory.get("id")
    print(f"Memory created. ID: {memory_id}")
    print(f"\nSet this environment variable:")
    print(f"  export CLIMATE_RAG_MEMORY_ID={memory_id}")


if __name__ == "__main__":
    main()
