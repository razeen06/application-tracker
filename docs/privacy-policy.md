# Privacy Policy for Application Tracker & Intern Copilot

**Last updated: July 15, 2026**

Application Tracker (the web dashboard) and Intern Copilot (its companion Chrome
extension) are a personal project for tracking job/internship applications.
This policy explains what data they collect, how it's used, and what control
you have over it.

## What data is collected

- **Google account info**: when you sign in with Google, we receive your email
  address and name from Google to create and identify your account. We do not
  receive or store your Google password.
- **Application data you track**: job title, company, URL, application
  status, notes, applied date, and any eligibility flags detected on a job
  page (see below). This is the data the dashboard and extension exist to
  manage.
- **API token**: a randomly generated token used to authenticate the Chrome
  extension to your account, so it can sync tracked applications without you
  signing in again in the browser.
- **Local extension storage**: the extension keeps a local copy of your
  tracked applications and detected flags in Chrome's built-in
  `chrome.storage.local`, so the popup works even if the server is briefly
  unreachable.

## What the Chrome extension does on pages you visit

The extension only runs on pages matching job-board/careers-page URL patterns
(or a specific site you've explicitly approved via its "Enable detection on
this site" prompt) — not on every page you browse. On those pages, it:

- Scans the visible page text for a small set of predefined phrases (e.g.
  mentions of a GPA/WAM cutoff, "unpaid", language suggesting a pay-to-play
  guarantee) to flag possible eligibility concerns, shown only to you in the
  extension popup.
- Looks for language suggesting you've just submitted an application (e.g.
  "thank you for applying") and asks whether to add it to your tracker — it
  never adds anything without you clicking "Yes."

This scanning happens locally in your browser. Only the application details
you choose to track (by clicking "Yes, track it" or the manual track button)
are sent to your account.

## How your data is used

Your data is used solely to provide the application-tracking functionality of
this tool for your own account. It is not sold, shared with third parties, or
used for advertising.

## Where your data is stored

Application data is stored in a database operated for this project. Session
login state uses a secure, HTTP-only cookie. The Chrome extension additionally
keeps a local copy in your browser via `chrome.storage.local`, which never
leaves your device except when syncing to your own account through the API.

## Third-party services

Signing in uses **Google OAuth** — Google's own privacy policy governs
whatever data Google itself processes during that sign-in. No analytics,
advertising, or tracking services are used by this project.

## Your control over your data

- You can delete any tracked application at any time from the dashboard or
  the extension popup.
- You can remove extension-approved sites at any time from the extension's
  Settings page.
- You can sign out at any time, which ends your browser session.
- To request deletion of your account and all associated data, contact
  razeenmustafiz135@gmail.com.

## Children's privacy

This tool is not directed at children and is not knowingly used to collect
data from anyone under 13.

## Changes to this policy

If this policy changes, the "Last updated" date above will be revised
accordingly.

## Contact

Questions about this policy or your data: razeenmustafiz135@gmail.com
