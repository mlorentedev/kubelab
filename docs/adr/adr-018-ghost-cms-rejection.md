---
id: "adr-018"
type: adr
status: active
tags: [web, cms, ghost, content-strategy]
owner: manu
created: "2026-03-28"
---

# ADR-018: Ghost CMS Rejected for Content Platform

## Status

Accepted 2026-03-03

## Context

When evaluating CMS options for the kubelab.live content platform (Spanish blog, newsletter, infoproducts), Ghost was a strong candidate due to its built-in newsletter, membership, and payment features. A thorough evaluation revealed critical blockers.

### Evaluation Criteria

1. **Newsletter delivery**: Must support custom SMTP or transactional email provider.
2. **Payments**: Must support one-time payments for infoproducts (not just subscriptions).
3. **Headless mode**: Must work as a headless CMS behind an Astro frontend.
4. **Operational simplicity**: Must fit the existing K3s + Docker infrastructure without heavy dependencies.

## Decision

**Reject Ghost CMS.** Continue with Astro + MDX content collections for both sites.

### Rejection Reasons

1. **Mailgun lock-in**: Ghost's newsletter feature is hardcoded to Mailgun. No support for Resend, SES, or generic SMTP for bulk newsletter sends. Transactional emails (welcome, password reset) can use custom SMTP, but the actual newsletter blast cannot.

2. **No one-time payments**: Ghost Payments (via Stripe) only supports recurring subscriptions. Selling a one-time infoproduct (PDF, course, template) requires external tooling (Lemon Squeezy, Gumroad), which defeats the purpose of Ghost's integrated commerce.

3. **Headless breaks memberships**: Using Ghost as a headless CMS (API → Astro frontend) loses the membership portal, payment flows, and newsletter signup forms. These are tightly coupled to Ghost's default Handlebars theme. Rebuilding them in Astro negates Ghost's value proposition.

4. **Operational overhead**: Ghost requires a Node.js process + MySQL/SQLite. On K3s this means a StatefulSet with persistent storage, memory overhead (~300-500MB), and another service to monitor. The current Astro static approach requires zero runtime processes.

### Chosen Alternative

| Concern | Solution |
|---------|----------|
| Blog content | Astro + MDX content collections (already working) |
| Newsletter | Evaluate Resend vs Listmonk (CONTENT-004) |
| Payments | Evaluate Lemon Squeezy (CONTENT-003) |
| Technical notes | MDX on mlorente.dev/notes (ADR-017) |

This composable approach avoids vendor lock-in and lets each concern be solved by the best tool for the job.

## Consequences

### Positive

- **No new infrastructure**: No MySQL, no Node process, no StatefulSet.
- **Vendor flexibility**: Free to choose best-in-class for email (Resend/Listmonk) and payments (Lemon Squeezy) independently.
- **Content in Git**: MDX files versioned alongside code. No database to back up or migrate.
- **Full control over frontend**: Astro components render exactly as designed, no theme constraints.

### Negative

- **No integrated CMS UI**: Authors must edit MDX files in a code editor (or Obsidian). No web-based editor for non-technical contributors (not a problem now — single author).
- **Newsletter and payments require separate integration work**: CONTENT-003 and CONTENT-004 tasks added to backlog.
- **No built-in membership portal**: If memberships are needed later, must be built from scratch or via a third-party service.

## References

- ADR-017: Domain Strategy
- [Ghost Mailgun Dependency](https://ghost.org/docs/faq/mailgun-newsletters/)
- [Ghost Memberships](https://ghost.org/docs/members/)
- CONTENT-003, CONTENT-004 tasks in `11-tasks.md`
