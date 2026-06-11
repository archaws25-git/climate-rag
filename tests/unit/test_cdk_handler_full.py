"""Additional tests for the CDK handler — covers edge cases and remaining branches."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cdk"))

from custom_resources.agentcore_handler.handler import on_event, is_complete


def _make_client_error(code):
    """Create a botocore ClientError with a given error code."""
    return ClientError(
        {"Error": {"Code": code, "Message": "test"}},
        "TestOperation",
    )


class TestOnEventUnsupportedType:
    """Tests for unsupported ResourceType handling."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_unsupported_type_returns_success(self, mock_client_fn):
        """Should return success with physical_id to avoid blocking the stack."""
        mock_client_fn.return_value = MagicMock()

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "some-id",
            "ResourceProperties": {"ResourceType": "UnknownThing"},
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "some-id"

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_unsupported_type_no_physical_id(self, mock_client_fn):
        """Should use 'na' when no PhysicalResourceId is provided."""
        mock_client_fn.return_value = MagicMock()

        event = {
            "RequestType": "Create",
            "ResourceProperties": {"ResourceType": "Invalid"},
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "na"


class TestOnEventMemoryEdgeCases:
    """Edge case tests for Memory on_event."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_delete_memory_not_found(self, mock_client_fn):
        """Should handle ResourceNotFoundException gracefully on delete."""
        mock_client = MagicMock()
        mock_client.delete_memory.side_effect = _make_client_error("ResourceNotFoundException")
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Delete",
            "PhysicalResourceId": "Memory-notfound123",
            "ResourceProperties": {
                "ResourceType": "Memory",
                "Name": "test",
                "EventExpiryDays": "30",
            },
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "Memory-notfound123"

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_update_memory_returns_physical_id(self, mock_client_fn):
        """Update should return the existing physical resource ID."""
        mock_client_fn.return_value = MagicMock()

        event = {
            "RequestType": "Update",
            "PhysicalResourceId": "Memory-existing123",
            "ResourceProperties": {
                "ResourceType": "Memory",
                "Name": "test",
                "EventExpiryDays": "30",
            },
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "Memory-existing123"
        assert result["Data"]["MemoryId"] == "Memory-existing123"


class TestOnEventCodeInterpreterEdgeCases:
    """Edge case tests for Code Interpreter on_event."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_delete_not_found(self, mock_client_fn):
        """Should handle ResourceNotFoundException gracefully on delete."""
        mock_client = MagicMock()
        mock_client.delete_code_interpreter.side_effect = _make_client_error("ResourceNotFoundException")
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Delete",
            "PhysicalResourceId": "CI-notfound12345",
            "ResourceProperties": {
                "ResourceType": "CodeInterpreter",
                "Name": "test",
            },
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "CI-notfound12345"

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_update_returns_physical_id(self, mock_client_fn):
        """Update should return the existing physical resource ID."""
        mock_client_fn.return_value = MagicMock()

        event = {
            "RequestType": "Update",
            "PhysicalResourceId": "CI-existing12345",
            "ResourceProperties": {
                "ResourceType": "CodeInterpreter",
                "Name": "test",
            },
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "CI-existing12345"
        assert result["Data"]["CodeInterpreterId"] == "CI-existing12345"


class TestOnEventGatewayEdgeCases:
    """Edge case tests for Gateway on_event."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_delete_not_found(self, mock_client_fn):
        """Should handle ResourceNotFoundException gracefully on delete."""
        mock_client = MagicMock()
        mock_client.list_gateway_targets.return_value = {"gatewayTargetSummaries": []}
        mock_client.delete_gateway.side_effect = _make_client_error("ResourceNotFoundException")
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Delete",
            "PhysicalResourceId": "GW-notfound12345",
            "ResourceProperties": {
                "ResourceType": "Gateway",
                "Name": "test",
                "RoleArn": "arn:aws:iam::123:role/test",
            },
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "GW-notfound12345"

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_update_gateway(self, mock_client_fn):
        """Update should delete existing targets and create new ones."""
        mock_client = MagicMock()
        mock_client.list_gateway_targets.return_value = {"gatewayTargetSummaries": [{"targetId": "old-target-1"}]}
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Update",
            "PhysicalResourceId": "GW-update123456",
            "ResourceProperties": {
                "ResourceType": "Gateway",
                "Name": "test",
                "RoleArn": "arn:aws:iam::123:role/test",
                "Targets": [],
            },
        }

        result = on_event(event, None)
        assert result["PhysicalResourceId"] == "GW-update123456"
        # Should have deleted the old target
        mock_client.delete_gateway_target.assert_called_once()


class TestIsCompleteGateway:
    """Tests for Gateway is_complete."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_gateway_active(self, mock_client_fn):
        """Should return IsComplete=True when gateway is ACTIVE."""
        mock_client = MagicMock()
        mock_client.get_gateway.return_value = {"status": "ACTIVE"}
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "GW-active123456",
            "ResourceProperties": {"ResourceType": "Gateway"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is True
        assert result["Data"]["GatewayId"] == "GW-active123456"

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_gateway_creating(self, mock_client_fn):
        """Should return IsComplete=False when gateway is still CREATING."""
        mock_client = MagicMock()
        mock_client.get_gateway.return_value = {"status": "CREATING"}
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "GW-creating12345",
            "ResourceProperties": {"ResourceType": "Gateway"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is False

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_gateway_failed_raises(self, mock_client_fn):
        """Should raise RuntimeError when gateway enters FAILED state."""
        mock_client = MagicMock()
        mock_client.get_gateway.return_value = {"status": "FAILED"}
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "GW-failed123456",
            "ResourceProperties": {"ResourceType": "Gateway"},
        }

        with pytest.raises(RuntimeError, match="FAILED"):
            is_complete(event, None)

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_code_interpreter_failed_raises(self, mock_client_fn):
        """Should raise RuntimeError when code interpreter enters FAILED."""
        mock_client = MagicMock()
        mock_client.get_code_interpreter.return_value = {"status": "FAILED"}
        mock_client_fn.return_value = mock_client

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "CI-failed123456",
            "ResourceProperties": {"ResourceType": "CodeInterpreter"},
        }

        with pytest.raises(RuntimeError, match="FAILED"):
            is_complete(event, None)


class TestIsCompleteUnsupported:
    """Tests for unsupported type in is_complete."""

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_unsupported_type_returns_complete(self, mock_client_fn):
        """Should return IsComplete=True for unknown types."""
        mock_client_fn.return_value = MagicMock()

        event = {
            "RequestType": "Create",
            "PhysicalResourceId": "unknown-id",
            "ResourceProperties": {"ResourceType": "InvalidType"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is True

    @patch("custom_resources.agentcore_handler.handler._client")
    def test_update_returns_complete_immediately(self, mock_client_fn):
        """Update in is_complete should return IsComplete=True immediately."""
        mock_client_fn.return_value = MagicMock()

        event = {
            "RequestType": "Update",
            "PhysicalResourceId": "some-id",
            "ResourceProperties": {"ResourceType": "Memory"},
        }

        result = is_complete(event, None)
        assert result["IsComplete"] is True
