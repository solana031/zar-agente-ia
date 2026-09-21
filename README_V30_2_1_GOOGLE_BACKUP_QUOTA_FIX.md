# ZAR v30.2.1 — Google backup quota resilience

Google services can remain connected while Gmail snapshotting hits a per-user quota. This release isolates Google backup by service: Gmail quota/rate-limit errors no longer abort Contacts, Calendar, Tasks, or Drive. The backup is marked `done_with_warnings`, successful services remain available locally, and the manifest records service-specific errors.
