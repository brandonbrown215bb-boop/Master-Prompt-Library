"""Master Prompt Library custom node package."""

__version__ = "2.1.0"

try:
    from .prompt_library_node import (
        MasterPromptImageExtractor,
        MasterPromptLibrary,
        MasterPromptLibraryV2,
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
    )
    from .routes import register_routes
except ImportError:  # direct source import for hermetic tests
    from prompt_library_node import (
        MasterPromptImageExtractor,
        MasterPromptLibrary,
        MasterPromptLibraryV2,
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
    )
    from routes import register_routes


WEB_DIRECTORY = "./web"

# ComfyUI creates PromptServer before loading custom nodes.  Keeping route
# registration here makes importing this package sufficient for installation;
# register_routes remains injectable for tests and hosts that load nodes later.
register_routes()


__all__ = [
    "__version__",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "MasterPromptLibrary",
    "MasterPromptLibraryV2",
    "MasterPromptImageExtractor",
    "WEB_DIRECTORY",
]
