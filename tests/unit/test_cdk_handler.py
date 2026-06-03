"""Tests for the CDK custom resource handler — AgentCore provisioner."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cdk"))

from custom_resources.agentcore_handler.handler import on_event, is_complete


class TestOnEventMemory:
    """Tests for Memory on_event handler."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_create_memory(self, mock_client_fn):
        """Should call create_memory and return the ID."""
        mock_client = MagicMock()
        mock_client.create_memory.return_value = {
            "memory": {"id": "ClimateRAGMemory-abc1234567"}
        }
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "ResourceProperties": {
                "ResourceType": "Memory",
                "Name": "ClimateRAGMemory",
                "EventExpiryDays": "30",
            },
        }

        result = on_event(event, None)

        assert result["PhysicalResourceId"] == "ClimateRAGMemory-abc1234567"
        assert result["Data"]["MemoryId"] == "ClimateRAGMemory-abc1234567"
        mock_client.create_memory.assert_called_once_with(
            name="ClimateRAGMemory",
            eventExpiryDuration=30,
        )

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_delete_memory(self, mock_client_fn):
        """Should call delete_memory with the physical resource ID."""
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Delete",
            "PhysicalResourceId": "ClimateRAGMemory-abc1234567",
            "ResourceProperties": {
                "ResourceType": "Memory",
                "Name": "ClimateRAGMemory",
                "EventExpiryDays": "30",
            },
        }

        result = on_event(event, None)

        mock_client.delete_memory.assert_called_once_with(
            memoryId="ClimateRAGMemory-abc1234567"
        )
        assert result["PhysicalResourceId"] == "ClimateRAGMemory-abc1234567"


class TestOnEventCodeInterpreter:
    """Tests for Code Interpreter on_event handler."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_create_code_interpreter(self, mock_client_fn):
        """Should call create_code_interpreter with networkConfiguration."""
        mock_client = MagicMock()
        mock_client.create_code_interpreter.return_value = {
            "codeInterpreterId": "ClimateChart-xyz9876543"
        }
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "ResourceProperties": {
                "ResourceType": "CodeInterpreter",
                "Name": "ClimateChartInterpreter",
            },
        }

        result = on_event(event, None)

        assert result["PhysicalResourceId"] == "ClimateChart-xyz9876543"
        assert result["Data"]["CodeInterpreterId"] == "ClimateChart-xyz9876543"
        mock_client.create_code_interpreter.assert_called_once_with(
            name="ClimateChartInterpreter",
            networkConfiguration={"networkMode": "PUBLIC"},
        )

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_delete_code_interpreter(self, mock_client_fn):
        """Should call delete_code_interpreter with the ID."""
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Delete",
            "PhysicalResourceId": "ClimateChart-xyz9876543",
            "ResourceProperties": {
                "ResourceType": "CodeInterpreter",
                "Name": "ClimateChartInterpreter",
            },
        }

        result = on_event(event, None)

        mock_client.delete_code_interpreter.assert_called_once_with(
            codeInterpreterId="ClimateChart-xyz9876543"
        )


class TestOnEventGateway:
    """Tests for Gateway on_event handler."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_create_gateway(self, mock_client_fn):
        """Should call create_gateway with all required params."""
        mock_client = MagicMock()
        mock_client.create_gateway.return_value = {
            "gatewayId": "ClimateGW-qwerty1234"
        }
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "ResourceProperties": {
                "ResourceType": "Gateway",
                "Name": "ClimateDataGateway",
                "RoleArn": "arn:aws:iam::123456789:role/gateway-role",
            },
        }

        result = on_event(event, None)

        assert result["PhysicalResourceId"] == "ClimateGW-qwerty1234"
        assert result["Data"]["GatewayId"] == "ClimateGW-qwerty1234"

        call_kwargs = mock_client.create_gateway.call_args[1]
        assert call_kwargs["protocolType"] == "MCP"
        assert call_kwargs["authorizerType"] == "NONE"
        assert call_kwargs["authorizerConfiguration"] == {}

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_delete_gateway(self, mock_client_fn):
        """Should delete targets then delete gateway."""
        mock_client = MagicMock()
        mock_client.list_gateway_targets.return_value = {
            "gatewayTargetSummaries": [
                {"targetId": "target-1"},
                {"targetId": "target-2"},
            ]
        }
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Delete",
            "PhysicalResourceId": "ClimateGW-qwerty1234",
            "ResourceProperties": {
                "ResourceType": "Gateway",
                "Name": "ClimateDataGateway",
                "RoleArn": "arn:aws:iam::123456789:role/gateway-role",
            },
        }

        result = on_event(event, None)

        # Should delete targets
        assert mock_client.delete_gateway_target.call_count == 2
        # Should delete gateway
        mock_client.delete_gateway.assert_called_once_with(
            gatewayIdentifier="ClimateGW-qwerty1234"
        )


class TestIsComplete:
    """Tests for the is_complete handler."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_memory_active(self, mock_client_fn):
        """Should return IsComplete=True when memory is ACTIVE."""
        mock_client = MagicMock()
        mock_client.get_memory.return_value = {
            "memory": {"status": "ACTIVE"}
        }
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "ClimateRAGMemory-abc1234567",
            "ResourceProperties": {"ResourceType": "Memory"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is True

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_memory_creating(self, mock_client_fn):
        """Should return IsComplete=False when memory is still CREATING."""
        mock_client = MagicMock()
        mock_client.get_memory.return_value = {
            "memory": {"status": "CREATING"}
        }
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "ClimateRAGMemory-abc1234567",
            "ResourceProperties": {"ResourceType": "Memory"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is False

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_code_interpreter_active(self, mock_client_fn):
        """Should return IsComplete=True when code interpreter is ACTIVE."""
        mock_client = MagicMock()
        mock_client.get_code_interpreter.return_value = {"status": "ACTIVE"}
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "ClimateChart-xyz9876543",
            "ResourceProperties": {"ResourceType": "CodeInterpreter"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is True
        assert result["Data"]["CodeInterpreterId"] == "ClimateChart-xyz9876543"

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_code_interpreter_creating(self, mock_client_fn):
        """Should return IsComplete=False when code interpreter is CREATING."""
        mock_client = MagicMock()
        mock_client.get_code_interpreter.return_value = {"status": "CREATING"}
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "ClimateChart-xyz9876543",
            "ResourceProperties": {"ResourceType": "CodeInterpreter"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is False

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_delete_always_complete(self, mock_client_fn):
        """Delete requests should return IsComplete=True immediately."""
        mock_client_fn.return_value = MagicMock()

        event = {
            "RequestType": "Delete",
            "PhysicalResourceId": "some-id",
            "ResourceProperties": {"ResourceType": "Memory"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is True

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_memory_failed_raises(self, mock_client_fn):
        """Should raise RuntimeError when memory enters FAILED state."""
        mock_client = MagicMock()
        mock_client.get_memory.return_value = {
            "memory": {"status": "FAILED"}
        }
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "ClimateRAGMemory-abc1234567",
            "ResourceProperties": {"ResourceType": "Memory"},
        }

        with pytest.raises(RuntimeError, match="FAILED"):
            is_complete(event, None)
