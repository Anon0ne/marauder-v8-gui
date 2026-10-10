# Captive portals

Default HTML page for the firmware's Evil Portal feature.

## `default/index.html` — awareness portal

A slick, self-contained captive-portal landing page in the app's dark theme. By
design it is a **security-awareness page, not a credential trap**: it asks for
nothing and collects nothing. When someone connects to the test AP and opens a
browser, they get a clear "you just connected to an unknown network in an
authorized test — here's why that's risky" message and a single acknowledge
button (purely client-side). It links back to the project on GitHub.

This is the intended "default portal": it demonstrates the captive-portal
vector for awareness and authorized assessments without phishing anyone.

### Use it

1. Copy `default/index.html` to the Marauder's SD card (e.g. as `portal.html`).
2. In the GUI: **WiFi → Attacks → Evil Portal — Set HTML** → `portal.html`.
3. **WiFi → Attacks → Evil Portal — Start**.

It's a single file with inline CSS/JS and no external resources, so it renders
with no internet connection (as captive portals must).

## Scope

Use the Evil Portal feature only on networks and engagements you own or are
explicitly authorized to test. This repository does not ship pages that imitate
real brands or capture credentials; if an authorized engagement needs that, that
work is on you and your rules of engagement, not bundled here.
