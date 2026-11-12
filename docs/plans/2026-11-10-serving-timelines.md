# Existing-log timeline comparison
User approved existing logs first, explicitly no new profiling. Compare control/MPS-only/static8/40 on native595/actualCUDA131 data only. No server changes.

- Use same raw round0 for default figure (not mean/synthetic timeline, not fastest-case selection); keep all5round selectable in standaloneHTML.
- Three settings × independentQwen/YOLOworker lanes. Exact stage boundaries from hostCLOCK_MONOTONIC: workerstart/modelstart/modelend, processingend derivedfromrecordedprocessingduration, workerend derivedfromloggedworker_busy_ms. Distinct resultreceipt marker. Qfirst-token phase boundary fromenqueue+serverTTFT; notpureGPU-prefill.
- Queue occupancy computed separately fromenqueue/dequeue events, not drawn as an exclusive workerstate. NoGPUkernels inferred from eventduration arrays or host model-call spans.
- PNG/SVG overview/commonaxis, first30s,first0.5s and queue-depth figures. SelfcontainedHTML zoom/range/round selector + hover exactrequest/stage/duration/UUID.
- Validate monotonic stageboundaries, no overlap ofsingleworkerintervals(allowfloatingtimestampguard), rawmakespanmatch, queuesnevernegative/end0, counts10/300. Unit tests first. Graphslabel hostactivitynotGPUoccupancy and first-tokenproductionnotstreamedclientTTFT. No newdependencies.
