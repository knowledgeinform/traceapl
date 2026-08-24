# TraceAPL Architecture Diagrams

This folder is the standardized, documented location for TraceAPL architectural diagrams and related visual design references.

Appropriate TraceAPL project staff with GitLab repository access should use this folder as the reference location for diagrams used in system understanding, security reviews, maintenance, deployment planning, and change-impact analysis.

## Current diagrams

- `traceapl-system-context.mmd` - high-level system context and external dependencies.
- `traceapl-deployment-architecture.mmd` - hosted application, browser clients, VM/network boundary, SQLite database, backups, Denodo, and SMTP interactions.
- `traceapl-auth-flow.mmd` - login, self-registration, built-in admin, remember-device, and admin-only access behavior.
- `traceapl-data-flow.mmd` - sample creation, lookup/scanning, handoff, characterization, export, backup, and audit-log data flows.

The `.mmd` files use Mermaid syntax and can be rendered in compatible Markdown tools, Mermaid CLI, or GitLab Mermaid previews where enabled.

## Maintenance procedure

Update the diagrams when a change materially affects any of the following:

- Hosting or deployment architecture.
- Authentication, authorization, sessions, or admin access.
- Data flows involving samples, characterization records, handoffs, exports, backups, or audit logs.
- External integrations, including Denodo REST, SMTP/email, HTTPS certificates, or barcode-scanner libraries.
- Database structure or retention behavior.
- CUI handling or boundary assumptions.

Diagram updates should be committed to GitLab with the related application change and referenced in the corresponding GitLab issue/merge request and `CHANGELOG.md` entry.

## Review note

These diagrams are project-maintained architecture references. They do not replace formal APL security architecture artifacts if separately required by the authorization process.
