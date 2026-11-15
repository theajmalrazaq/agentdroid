"""AgentDroid: silent Android device (Redroid) that local AI agents drive directly."""

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.mcp import McpServer
from agentdroid.pipeline import CompoundPipeline, PipelineSpec
from agentdroid.watcher import LiveWatcher

__version__ = "0.3.0"
__all__ = [
    "AccessibilityHelperClient",
    "AdbDevice",
    "AndroidEngine",
    "CompoundPipeline",
    "LiveWatcher",
    "McpServer",
    "PipelineSpec",
]
