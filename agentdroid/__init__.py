"""AgentDroid: silent Android device (Redroid) that local AI agents drive directly."""

from agentdroid.adb import AdbDevice
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.pipeline import CompoundPipeline, PipelineSpec
from agentdroid.watcher import LiveWatcher

__version__ = "0.3.0"
__all__ = [
    "AccessibilityHelperClient",
    "AdbDevice",
    "CompoundPipeline",
    "LiveWatcher",
    "PipelineSpec",
]
