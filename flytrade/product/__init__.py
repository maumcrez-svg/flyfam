"""The product surface: the frozen trader running continuously, and its feed.

``flytrade.pons`` is the environment and the loop; this package is what turns
one live paper loop into something a spectacle can read — a day journal, a
state file, a rolling request window and a driver that throttles and retries
instead of stopping. Nothing here decides anything: every decision is still
:class:`flytrade.pons.loop.PonsLoop`'s, on the frozen ``trader-v1`` brain.
"""

VERSION = "flytrade_product_v1"

__all__ = ["VERSION"]
