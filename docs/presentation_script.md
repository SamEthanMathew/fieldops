# FieldOps 3-Minute Presentation Script

## 0:00-0:30 Problem

"In a mass casualty incident, the bottleneck is not medical skill alone. It is information coordination during the golden hour. The Medical Branch Director is trying to track patients, ambulances, and hospital capacity in real time while conditions change by the minute. That is a combinatorial optimization problem under extreme stress.

A 2022 JACS analysis of NEMSIS data found that only 56% of critically injured patients in the studied cohort were transported directly to trauma centers. Boston showed what good coordination can do: JAMA reported casualties were transported to hospitals within 90 minutes, and no patient who arrived alive at a hospital later died. Route 91 showed the opposite challenge, with many victims reaching hospitals by private vehicle or rideshare, which complicated patient tracking and hospital awareness. FieldOps is built for that bottleneck."

## 0:30-1:00 System

"FieldOps is a multi-agent co-pilot for MCI command.

The Triage agent classifies patients with structured, citation-backed outputs.
The Hospital Intel agent maintains live capacity, diversions, and specialty coverage.
The Logistics agent recommends patient-to-ambulance-to-hospital matches and keeps alternatives.
The Overwatch agent watches the whole incident, raises alerts, and produces SITREPs.

They do not call each other directly. They coordinate through a shared incident state, so we get traceability, replayability, and graceful degradation."

## 1:00-2:10 Demo

"We are running the Pittsburgh bridge collapse scenario. Patients appear over time, triage reasoning lands in the log, ambulances and hospitals update on the map, and RED dispatches require human approval.

We can inject a hospital diversion, an ambulance failure, stale hospital data, or an agent timeout. When that happens, pending routes are released, the system re-optimizes, and Overwatch updates the SITREP.

This is not a static one-shot plan. It is a living dispatch picture."

## 2:10-2:40 Results

"On the standard scenario, FieldOps achieved:

- Triage accuracy: 1.00
- Transport match score: 0.964
- Mean dispatch latency: 0.0 seconds for assignment recommendations
- Hospital load gini: 0.179
- Survival proxy: 0.954

Against the same scenario, the naive baseline reached:

- Transport match score: 0.679
- Hospital load gini: 0.833
- Survival proxy: 0.717

That is roughly a 33% improvement in the survival proxy while staying above the routing and balancing thresholds we set up front."

## 2:40-3:00 Risks and Tradeoffs

"We designed for conservative safety. RED dispatches stay human-approved. Triage is structured and citation-backed. If a hospital diverts or an ambulance drops out, routes are released and recomputed. If an agent degrades, the rest of the system keeps operating.

The key tradeoff is speed versus certainty. We chose fast, auditable recommendations with human oversight for the highest-stakes calls. FieldOps is not replacing the incident commander. It is helping them see and decide faster than a clipboard and radio can."
