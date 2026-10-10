"""Select native function storage and resolve OTF1 process aliases."""

from functools import cached_property
import collections

from . import limits
from ..trace.otf1_aliases import Otf1ProcessAliases
from .series import Data
from .span_sources import stack_function_source
from .stack_sources import count_endpoint, function_mode
from .state_records import StateRecordStore
from .state_tree import StateTreeSource


class FunctionSources:
    """Own lazy native record stores and per-location Stack/Tree caches."""

    def __init__(self, context):
        self.context = context
        self.state_tree_cache = {}
        self.state_tree_present = {}
        self.state_tree_mixed = {}

    def function_source(self, kind, spec):
        ctx = self.context
        before = (
            self.records.diagnostics.copy()
            if "records" in self.__dict__
            else collections.Counter()
        )
        result = self.function_source_resolved(kind, spec)
        if "records" in self.__dict__:
            changed = self.records.diagnostics - before
            if changed:
                ctx.source_diagnostics.append(
                    dict(
                        source=ctx.source_names[-1] if ctx.source_names else kind,
                        location="all",
                        kind=kind,
                        skipped={},
                        uncertain=dict(changed),
                    )
                )
        return result

    @cached_property
    def records(self):
        ctx = self.context
        return StateRecordStore(
            ctx.trace, ctx.fetch, ctx.charge, limits.MAX_INPUT_POINTS
        )

    @cached_property
    def aliases(self):
        ctx = self.context
        return Otf1ProcessAliases.from_definitions(ctx.trace.defs, ctx.charge)

    def function_source_resolved(self, kind, spec):
        ctx = self.context
        aliases = self.aliases
        if not aliases.aliases:
            return self.function_source_storage(kind, spec)
        _, requested = ctx.scoped(spec)
        mapped = {loc: aliases.canonical(loc) for loc in requested}
        canonical = list(dict.fromkeys(mapped.values()))
        if any(loc not in ctx.trace.locations for loc in canonical):
            raise ValueError(
                "OTF1 substituted function location is missing from the trace index"
            )
        original = ctx.locations
        diagnostic_start = len(ctx.source_diagnostics)
        try:
            # Constructors resolve core location+2c once. A representative is
            # allowed outside the user's selected display locations, and a
            # second alias on that representative must not be followed.
            ctx.locations = canonical
            result = self.function_source_storage(kind, dict(spec, locations=canonical))
        finally:
            ctx.locations = original
        diagnostics = ctx.source_diagnostics[diagnostic_start:]
        del ctx.source_diagnostics[diagnostic_start:]
        for diagnosis in diagnostics:
            matches = [
                loc
                for loc, target in mapped.items()
                if target == diagnosis.get("location")
            ]
            ctx.source_diagnostics.extend(
                dict(diagnosis, location=loc, sourceLocation=mapped[loc])
                for loc in matches
            )
            if not matches:
                ctx.source_diagnostics.append(diagnosis)
        if aliases.skipped:
            ctx.source_diagnostics.append(
                dict(
                    source=ctx.source_names[-1] if ctx.source_names else kind,
                    location="all",
                    kind=kind,
                    skipped={
                        "otf1-" + key: value for key, value in aliases.skipped.items()
                    },
                )
            )
        return Data(
            {
                loc: result.series[target]
                for loc, target in mapped.items()
                if target in result.series
            },
            result.unit,
        )

    def function_source_storage(self, kind, spec):
        ctx = self.context
        q, locs = ctx.scoped(spec)
        storage = spec.get("functionStorage", "native")
        if storage not in ("native", "per-location"):
            raise ValueError("Function storage must be native or per-location")
        # e9a650 switches the entire session as soon as any recorded context
        # definition is registered. Normal Enter records remain in Stack
        # storage; there is no per-location fallback in the native factory.
        native_tree = storage == "native" and bool(ctx.trace.defs.get("CallingContext"))
        records = {}
        for loc in locs:
            if loc not in self.state_tree_cache:
                present = next(
                    ctx.fetch(
                        "SELECT count(*) n FROM events WHERE location=? AND kind IN "
                        + "('CallingContextEnter','CallingContextLeave','CallingContextSample')",
                        (loc,),
                    )
                )["n"]
                self.state_tree_present[loc] = present
                self.state_tree_cache[loc] = (
                    self.records.tree(loc) if native_tree or present else []
                )
                self.state_tree_mixed[loc] = next(
                    ctx.fetch(
                        "SELECT count(*) n FROM events WHERE location=? AND kind IN ('Enter','Leave')",
                        (loc,),
                    )
                )["n"]
            if self.state_tree_present[loc] or native_tree:
                if not self.state_tree_cache[loc]:
                    self.state_tree_cache[loc] = self.records.tree(loc)
                records[loc] = self.state_tree_cache[loc]
            if ctx.trace.defs.get("CallingContext") and self.state_tree_mixed[loc]:
                diagnostic = dict(
                    source=ctx.source_names[-1] if ctx.source_names else kind,
                    location=loc,
                    kind=kind,
                    skipped={},
                )
                if loc in records:
                    diagnostic["skipped"] = {
                        "instrumented-function-events-outside-native-storage": self.state_tree_mixed[
                            loc
                        ]
                    }
                else:
                    diagnostic["extensions"] = {
                        "per-location-function-storage": self.state_tree_mixed[loc]
                    }
                ctx.source_diagnostics.append(diagnostic)
        if not records or spec.get("impulses") in (True, 1, "1", "true"):
            return stack_function_source(ctx, kind, spec)
        selected = ctx.selected_regions(q, spec)
        if kind in ("function_attribute", "function_attribute_active"):
            result = {}
            for loc, events in records.items():
                values = ctx.state_tree_properties(loc, events, selected, kind, spec)
                if values is None:
                    ctx.source_diagnostics.append(
                        dict(
                            source=ctx.source_names[-1] if ctx.source_names else kind,
                            location=loc,
                            kind=kind,
                            skipped={},
                            uncertain={"state-tree-attribute-producer": 1},
                        )
                    )
                    continue
                source = StateTreeSource(
                    events,
                    selected,
                    0,
                    ctx.charge,
                    values,
                    self.records.tick_seconds,
                )
                result[loc] = ctx.state_source_series(source)
            rest = [loc for loc in locs if loc not in result]
            fallback = (
                stack_function_source(ctx, kind, dict(spec, locations=rest))
                if rest
                else Data({})
            )
            result.update(fallback.series)
            return Data(result, fallback.unit)
        inclusive = spec.get("inclusive", False) in (True, 1, "1", "true")
        if kind == "function_count":
            mode = {"enter": 5, "leave": 6, "both": 7}[count_endpoint(spec)]
        else:
            mode = 8 if kind == "function_hits" else function_mode(kind, inclusive)
        rest = [loc for loc in locs if loc not in records]
        result = (
            stack_function_source(ctx, kind, dict(spec, locations=rest)).series
            if rest
            else {}
        )
        for loc, events in records.items():
            source = StateTreeSource(
                events,
                selected,
                mode,
                ctx.charge,
                tick_seconds=self.records.tick_seconds,
            )
            result[loc] = ctx.state_source_series(source)
        return Data(
            result, "count" if mode >= 5 else "s" if kind == "function_duration" else ""
        )
