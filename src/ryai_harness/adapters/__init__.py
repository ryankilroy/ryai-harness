"""Backend Adapters.

One module per Backend (CONTEXT.md: "One Adapter per Backend. An Adapter
holds no project knowledge and is the entire cost of adopting a new
Backend."). Nothing outside a Backend's own adapter module may reference
that Backend's wire dialect — each Backend's adapter test suite carries a
grep-based check that keeps this true as the codebase grows.
"""

from __future__ import annotations
