
### Retention production delete boundary
Production log deletion is permitted only through the authenticated retention boundary after explicit owner authorization. The boundary accepts only dated Traccar historical log names, protects the active log by construction, revalidates eligibility and file identity immediately before unlink, and has no network or shell capability. systemd confines writable paths to `/opt/traccar/logs` and the boundary runtime directory.
