"""Directed payload and collective-arrival prerequisites for wait records."""

import collections

from ..causality.lazy_causes import BarrierCohort, CauseCollection
from ..causality.operations import operation
from .communicators import Communicators
from .collective_causes import (
    plan as collective_payload_plan,
    OPERATIONS as PAYLOAD_OPERATIONS,
    PrefixPlan,
)
from .intercomm import plan as intercomm_plan, IntercommPlan
from .prefix_causes import PrefixCohort
from .wait_models import WAIT


class CollectiveWaits:
    def __init__(self, trace, lookup, records, completions, diagnostics):
        self.trace = trace
        self.lookup = lookup
        self.records = records
        self.completions = completions
        self.diagnostics = diagnostics

    def analyze(self, collective_records, collectives):
        self.plan(collectives)
        self.blocking(collective_records)
        self.nonblocking(collectives)
        return self.causes(collective_records, collectives)

    def plan(self, collectives):
        self.payload_plans = {}
        self.payload_by_event = {}
        resolver = Communicators(self.trace.defs)
        for cohort in collectives:
            if cohort["evidence"]["intercommunicator"]:
                payload, status = intercomm_plan(cohort, resolver)
            else:
                if (
                    cohort["operation"].upper().removeprefix("MPI_")
                    not in PAYLOAD_OPERATIONS
                ):
                    continue
                payload, status = collective_payload_plan(cohort, resolver)
            cohort["payloadDependencies"] = status
            if payload is not None:
                self.payload_plans[cohort["id"]] = payload
                for participant in cohort["participants"]:
                    self.payload_by_event[participant["event"]] = (payload, participant)
                if payload.clock_invalid:
                    self.diagnostics["collective_payload_clock_inversion"] += len(
                        payload.clock_invalid
                    )
            elif status["code"] not in (
                "cohort-unresolved",
                "record-contract-unresolved",
            ):
                self.diagnostics["collective_" + status["code"].replace("-", "_")] += 1

    def blocking(self, collective_records):
        for record in collective_records:
            event = record.evidence["event"]
            if event not in self.payload_by_event:
                continue
            payload, participant = self.payload_by_event[event]
            record.evidence["collectivePayload"] = payload.evidence
            identity = participant["participant"]
            if identity not in payload.targets:
                record.evidence["arrivalEstimate"] = (
                    "No incoming remote-group prerequisite is established for this participant; its routine remains an observation."
                    if isinstance(payload, IntercommPlan)
                    else (
                        "Local output is not proven nonempty; any last-arrival estimate remains conditional on the unrecorded collective protocol."
                        if payload.evidence.get("producerContract")
                        == "scorep-10.0-reduce-scatter-bytes"
                        else "Outgoing-only data role; any last-arrival delay remains conditional on the unrecorded collective protocol."
                    )
                )
                continue
            peer = payload.latest_for(identity)
            record.inferred_end = record.span.start
            if identity in payload.clock_invalid:
                record.confidence = "unavailable"
                record.evidence["payloadClockInversion"] = True
            elif peer is not None:
                record.inferred_end = max(record.span.start, peer["start"])
                record.category = "collective_payload_wait"
                record.peer = peer["initiationLocation"] or peer["location"]
                record.confidence = "recorded-payload-prerequisite"

    def nonblocking(self, collectives):
        for cohort in collectives:
            valid = cohort["confidence"] == "conditional"
            latest = max(p["start"] for p in cohort["participants"])
            peer = max(cohort["participants"], key=lambda p: p["start"])["location"]
            for participant in cohort["participants"]:
                if not participant["nonblocking"]:
                    continue
                request = self.completions.get(participant["event"])
                if (
                    request is None
                    or request.status != "completed"
                    or request.kind != "collective"
                ):
                    continue
                span = request.completion_span
                if (
                    span is None
                    or span.routine not in WAIT
                    or span.id not in self.records
                ):
                    continue
                record = self.records[span.id]
                payload = self.payload_plans.get(cohort["id"])
                directed = (
                    payload is not None
                    and participant["participant"] in payload.targets
                )
                dependency_peer = (
                    payload.latest_for(participant["participant"]) if directed else None
                )
                dependency_time = (
                    dependency_peer["start"] if dependency_peer is not None else latest
                )
                evidence = record.evidence.setdefault("collectiveDependencies", [])
                if len(evidence) < 16:
                    evidence.append(
                        dict(
                            collective=cohort["id"],
                            completionEvent=participant["event"],
                            lastInitiation=latest,
                            completeCohort=valid,
                            payload=payload.evidence if payload else None,
                        )
                    )
                if directed and (
                    participant["participant"] in payload.clock_invalid
                    or dependency_peer is None
                ):
                    continue
                if (
                    (valid or directed)
                    and dependency_time <= participant["end"]
                    and span.complete
                ):
                    deadline = min(span.end, max(span.start, dependency_time))
                    if deadline > record.inferred_end:
                        record.inferred_end = deadline
                        record.category = (
                            "collective_payload_wait"
                            if directed
                            else "collective_arrival_wait"
                        )
                        record.confidence = (
                            "conditional"
                            if not directed or span.routine in {"waitany", "waitsome"}
                            else "recorded-payload-prerequisite"
                        )
                        record.peer = (
                            (
                                dependency_peer["initiationLocation"]
                                or dependency_peer["location"]
                            )
                            if dependency_peer
                            else peer
                        )

    def causes(self, collective_records, collectives):
        # Prefer explicit collective event brackets where present, retaining the
        # observed routine as a fallback when the producer omitted those records.
        collective_records_by_id = collections.defaultdict(
            lambda: collections.defaultdict(list)
        )
        for record in collective_records:
            collective_records_by_id[record.evidence["collective"]][
                record.span.location
            ].append(record)
        shared_cause_weight = 0

        def source_lookups(cohort):
            # Every peer of an analyzed cohort; a superset of the lookups below.
            if cohort["confidence"] == "conditional" or isinstance(
                self.payload_plans.get(cohort["id"]), IntercommPlan
            ):
                for peer in cohort["participants"]:
                    location = peer["initiationLocation"] or peer["location"]
                    yield location, peer["start"], None, peer["initiationEvent"]

        for cohort in self.lookup.prefetched(collectives, source_lookups, size=64):
            payload = self.payload_plans.get(cohort["id"])
            intercomm = isinstance(payload, IntercommPlan)
            if cohort["confidence"] != "conditional" and not intercomm:
                continue
            barrier = cohort["operation"].upper() in ("BARRIER", "MPI_BARRIER")
            latest = max(p["start"] for p in cohort["participants"])
            sources = []
            payload_sources = []
            for peer in cohort["participants"]:
                # Other collectives retain only their existing conditional latest
                # arrival estimate; their full dataflow is not inferred from rank.
                use_default = not intercomm and (barrier or peer["start"] == latest)
                use_payload = (
                    payload is not None and peer["participant"] in payload.sources
                )
                if not use_default and not use_payload:
                    continue
                peer_location = peer["initiationLocation"] or peer["location"]
                source_span = self.lookup.at(
                    peer_location, peer["start"], event=peer["initiationEvent"]
                )
                source = operation(
                    source_span,
                    location=peer_location,
                    event=peer["initiationEvent"],
                    time=peer["start"],
                    routine=cohort["operation"],
                )
                source.extra = dict(
                    collectiveParticipant=peer["participant"],
                    sizeSent=peer["sizeSent"],
                    sizeReceived=peer["sizeReceived"],
                    initiationRoutine=peer["initiationRoutine"],
                    initiationSpan=peer["initiationSpan"],
                    initiationRoutineComplete=peer["initiationRoutineComplete"],
                    initiationName=peer["initiationName"],
                    initiationParadigm=peer["initiationParadigm"],
                )
                item = (peer["participant"], source, peer["start"])
                if use_default:
                    sources.append(item)
                if use_payload:
                    payload_sources.append(item)
            shared = BarrierCohort(
                cohort["id"],
                cohort["comm"],
                sources,
                kind="barrier_arrival" if barrier else "collective_arrival",
                reason=(
                    "A barrier cannot complete before every communicator participant enters."
                    if barrier
                    else "Collective initiation skew alone does not establish this participant’s data dependency on the peer; root, direction and payload semantics may differ."
                ),
                expected_prerequisites=len(cohort["participants"]) - 1,
            )
            shared_cause_weight += shared.storage_weight
            directed_shared = None
            intercomm_shared = {}
            if intercomm:
                intercomm_shared, weight = payload.shared_views(
                    cohort["id"], cohort["comm"], payload_sources
                )
                shared_cause_weight += weight
            elif payload is not None:
                cohort_type = (
                    PrefixCohort if isinstance(payload, PrefixPlan) else BarrierCohort
                )
                prefix_args = (
                    dict(ranks=payload.prefix_ranks)
                    if isinstance(payload, PrefixPlan)
                    else {}
                )
                directed_shared = cohort_type(
                    cohort["id"],
                    cohort["comm"],
                    payload_sources,
                    kind="collective_payload",
                    reason=payload.reason,
                    expected_prerequisites=payload.expected,
                    extra=dict(payload=payload.evidence),
                    **prefix_args,
                )
                shared_cause_weight += directed_shared.storage_weight
            for participant in cohort["participants"]:
                directed = (
                    payload is not None
                    and participant["participant"] in payload.targets
                )
                if intercomm and not directed:
                    continue
                if directed and participant["participant"] in payload.clock_invalid:
                    continue
                target_records = []
                if participant["nonblocking"]:
                    request = self.completions.get(participant["event"])
                    if (
                        request
                        and request.status == "completed"
                        and request.completion_span
                        and request.completion_span.routine in WAIT
                    ):
                        record = self.records.get(request.completion_span.id)
                        if record:
                            target_records.append((record, request))
                else:
                    target_records = [
                        (r, None)
                        for r in collective_records_by_id[cohort["id"]].get(
                            participant["location"], ()
                        )
                    ]
                for record, request in target_records:
                    if not record.span.complete:
                        continue
                    target = operation(record.span, event=participant["event"])
                    target.span = record.evidence.get("span") or target.span
                    target.extra = dict(
                        collectiveParticipant=participant["participant"],
                        sizeSent=participant["sizeSent"],
                        sizeReceived=participant["sizeReceived"],
                    )
                    selected_shared = (
                        intercomm_shared[participant["participant"]]
                        if intercomm
                        else directed_shared if directed else shared
                    )
                    view = selected_shared.view(
                        participant["participant"],
                        target,
                        record.span.id,
                        required=(barrier or directed)
                        and record.span.routine not in {"waitany", "waitsome"},
                        request=(
                            dict(id=request.request, generation=request.generation)
                            if request
                            else None
                        ),
                    )
                    if view:
                        if not isinstance(record.causes, CauseCollection):
                            record.causes = CauseCollection(record.causes)
                        record.causes.append(view)
        return shared_cause_weight
