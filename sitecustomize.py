"""Site configuration for suppressing noisy third-party warnings."""

import warnings

warnings.filterwarnings(
    "ignore",
    message="Please use `import python_multipart` instead.",
    category=PendingDeprecationWarning,
)
