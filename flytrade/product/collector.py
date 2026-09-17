"""Observation-only extension for systematic follow-up windows.

These curves remain excluded by the unchanged neural admission age limit.
Pins do not become held positions and expire even if observations are missing.
"""
from ..pons.collector import Collector


class ProductCollector(Collector):
    followup_until = None

    def tracked(self, now_ts):
        curves = set(super().tracked(now_ts))
        for curve, deadline in (self.followup_until or {}).items():
            record = self.launches.get(curve)
            if (deadline >= now_ts and record is not None
                    and curve not in self.completed
                    and (self.quote_filter is None
                         or record.get('quote_asset') == self.quote_filter)):
                curves.add(curve)
        return sorted(curves)
