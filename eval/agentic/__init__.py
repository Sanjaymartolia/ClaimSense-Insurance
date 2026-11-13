"""Evaluation of how the pipeline uses its tools: order, arguments, permissions, hooks, results.

Forces the stub LLM before any agent is imported, because `get_llm` is cached per role and a key
in the environment would otherwise turn on paid calls. Everything in this package is offline.
"""

import os

os.environ["CLAIMSENSE_LLM"] = "stub"
