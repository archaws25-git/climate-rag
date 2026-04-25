#!/bin/bash
# Deploy ClimateRAG agent to AgentCore Runtime
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
AGENT_DIR="$PROJECT_DIR/agent"

echo "=== ClimateRAG Deployment ==="
echo "Agent directory: $AGENT_DIR"

cd "$AGENT_DIR"

echo ""
echo "Step 1: Testing agent locally..."
echo "  Run 'agentcore dev' in one terminal"
echo "  Run 'agentcore invoke --dev \"{\\\"prompt\\\": \\\"What is the global temperature trend?\\\"}\"' in another"
echo ""

read -p "Press Enter to deploy to AgentCore Runtime (or Ctrl+C to cancel)..."

echo ""
echo "Step 2: Deploying to AgentCore Runtime..."
agentcore launch

echo ""
echo "Step 3: Testing deployed agent..."
agentcore invoke '{"prompt": "What is the global temperature trend since 1950?"}'

echo ""
echo "=== Deployment complete ==="
echo "Check CloudWatch for traces and logs."
