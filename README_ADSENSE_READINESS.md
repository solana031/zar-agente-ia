# ReposNews AdSense readiness — 33.3.122

Scope: consent compatibility and three existing owner actions. No Google account edits, resubmission, Auto Ads or ad slots.

- SITE_READY_FOR_ADSENSE describes the six verified public-site checks. CMP, legal identity and account/tax review remain separate gates.
- REVERIFICAR ADSENSE / CMP opens the public site. An authenticated owner session, CSRF, a short-lived single-use challenge, source-window and origin checks bind the sanitized TCF result. Server checks are restricted to three fixed public URLs. No private Google/tax requests occur.
- TCF ping and addEventListener detect loaded/readable state, CMP ID, event and presence of a TC string. No TC strings or visitors' choices are stored. Missing/stub/error/unverified CMPs fail closed. Google CMP 300 is the certified provider prepared here; another ID requires review.
- Consent defaults to denied. Google FC consent-mode values map granular grants; rejection returns to denied. Ads remain inert even after all readiness gates pass: Google account/site approval and ad activation are separate, unverified requirements.
- Current Google onboarding lacks Privacy & messaging. The CMP action explains the conditional menu and message-publication steps. With AdSense disabled, the message also needs an independent official CMP tag supplied by Google; saving only its matching public Funding Choices URL is supported. Publishing a message alone cannot execute an inert ad tag. No loader is invented or enabled automatically.
- The public legal form is empty until explicitly filled/authorized by the owner. Only the allowlisted PUBLIC_REQUIRED fields render; private administrative data is never imported. Economic activity requires the identification fields described by LSSI article 10; registry and professional obligations need owner applicability review. This is an owner attestation, not legal certification.
- Account review stores booleans and an explicit tax status, never names, addresses, documents or bank/payment details. TAX INFO stays UNKNOWN without current acceptance evidence; accepted/not-applicable status must be personally checked. No Spanish residence or treaty benefit is inferred.
- The three stable notification keys are updated/deduplicated. Completion follows evidence, not manually marking a notification done. All three plus current public evidence are required for READY_FOR_RESUBMISSION. Google is never submitted automatically.
- The 121 public crawl is reused only while fresh and its public-input fingerprint still matches; changing the code version alone does not invalidate that crawl. Public rechecks do not silently refresh content-audit proof.

References:
- https://developers.google.com/funding-choices/fc-api-docs
- https://support.google.com/adsense/answer/13554116
- https://support.google.com/adsense/answer/10960768
- https://github.com/InteractiveAdvertisingBureau/GDPR-Transparency-and-Consent-Framework/blob/master/TCFv2/IAB%20Tech%20Lab%20-%20CMP%20API%20v2.md
- https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758#a10

Validation: focused pytest suites; offline TCF contract; browser desktop/mobile public pages, owner checklist and cross-origin reverify popup with mocked network. Production deployment and observed states are reported separately.
