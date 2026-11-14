"""AgentDroid: Silent AI-Agent Usable Android Device (Redroid + Google Artemis)."""

from agentdroid.adb import AdbDevice
from agentdroid.artemis_bridge import ArtemisBridge
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.pipeline import CompoundPipeline, PipelineSpec
from agentdroid.watcher import LiveWatcher

__version__ = "0.2.0"
__all__ = [
    "AccessibilityHelperClient",
    "AdbDevice",
    "ArtemisBridge",
    "CompoundPipeline",
    "LiveWatcher",
    "PipelineSpec",
]
