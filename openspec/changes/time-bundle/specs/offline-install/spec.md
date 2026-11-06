## MODIFIED Requirements

### Requirement: No runtime calls to the internet

With an offline providers file, `AUTH_MODE=oidc` against an issuer inside the install, no connector outside it, and web push off (no VAPID keys set), neither server SHALL make any network call outside the install while it runs. The frontend image SHALL be built and run with Next.js telemetry turned off. Every page SHALL load its fonts, scripts, and styles from the app's own address, and SHALL NOT reference a font service or other outside host.

#### Scenario: Pages use only the app's address

- **WHEN** a page of the app is loaded
- **THEN** every script, style, and font it loads is served by the app
- **AND** neither the page nor its styles reference `fonts.googleapis.com` or `fonts.gstatic.com`

#### Scenario: Telemetry is off

- **WHEN** the frontend image runs
- **THEN** `NEXT_TELEMETRY_DISABLED` is set to `1` in its environment

#### Scenario: Reminders in an offline install

- **WHEN** an offline install with no VAPID keys set has a reminder come due
- **THEN** the reminder appears in the app's notification list, and neither server makes a network call outside the install
