# Native595 MPS STATIC only: end-to-end validation and complete comparison

User requests ALL stages and final results. No Green API in generated model sources. Old pre-upgrade/compat experiments retained separately and never pooled.

Environment: kernel7.0.0-1025-nvidia,driver595.99.02,Toolkit13.1.2,nvcc13.1.115. Immutable model images torch buildCUDA13.0; mount actual13.1 runtime identically for ALL cases; verify actualcudaRuntimeGetVersion13010, not infer fromtorch.version.cuda.

Gate1 passed: native13.1 runtime/13.2driver API, static16/32 device-visibleSMcounts, kernel42 both, excess1chunk rejected; actualGB10chunk2SM. Docker image native131 runtime+static counts must pass too.

Experiment design: noMPS control,MPS-only,no static,and static Q/Y8/40,16/32,24/24,32/16,40/8. 5 complete randomized blocks seed20261110,35trials. Each entry reloadboth/warm simultaneousQ3Y30, measured simultaneousQ10Y300. Same512input/128forcedoutput,bus640/b1,Q16/Y512DDS512/domain74,PyTorchBF16/FP16stockbackends,eventinstrumentation. No solo traffic. No Nsight in timedruns. Full35warmups+35bursts=12005validatedresponses.

Private same-UID MPSdaemon native/usr/bin, start -S onlystatic; create bothcomplementarypartitionsBEFOREfirstclient. Stopmodels and drainallclients before changingdaemon/partitions. No active-thread percentage,no compatibilityuserlib,no Green code. Check membership equals actualknownhostmodelPIDs (notmerely2arbitrary clients), advertisedpartitionID and SMcount metadata; source/image hashes. GlobalownedGPUlock, boundedstages/global4hdeadline; host1Hzresources; full livepublications; Slack progress/failure; preservepartial failures with no replacement/pooling.

Gate2 actualmodels: profile static16/32 pairedQ10/Y300, per-modelCUPTI/noGreenId, bracketedCLOCK_MONOTONIC anchors,contextswitch+GPUmetrics separatecollector. Validate overlap without reading kernelspanoverlapalone asphysicalproof. Includeclockerrors. Timingsdiagnosticonly. Existing tested file-gatedcapturereused. Ifprofilerunsupported fails, do not inventparallelproof.

Performance: requestE2Ep95/mean/queue,modelcompletion,totalmakespan; Qprefill/decode/TTFT/TPOT;Yforward/pre/post;non-overlappinghostE2Ecomponents separately fromnestedGPUeventforwardspan (notpureSMactive). Exactly5independentbursts/case,showalltrialsanddispersion;3%mean-total tie heuristic thenYcompletion,alsoPareto andtie0/1/3/5%sensitivity. Pairedround comparisons toMPS-only andcontrol, no small-Nsignificanceclaims.

Gate3 finalist selectedfromunprofileddata, separatetrace onlyifdifferentfrom16/32 andMPS-only ifselected. Timeddatafixedbeforeprofiling,trace notpooled. Newdriver baseline freshlymeasured; noold595/580 comparisons interpretedcausally.

Restoration: originalnormal-serving templates savedfrombeforeupgrade; restore MPSuserunit enabled/active,exactQ/Ytemplates/replicas1anddomain42actualnativeROShealth. Do not silentlychoose/deploynewSMpolicy beforeuserreview. ArchivelocalrawCSV/plots/report/versions/hash/audit; previousbaseline677filesunchanged,noGitpush. ~3hours reload/work budget; durable status and boundedcontroller.
