#!/usr/bin/env bash
# Capture the documentation screenshots from a running Nabz server.
#
# Three things make this fiddly, and all three are handled below.
#
# 1. The browser session does not survive between separate shell invocations.
#    One `agent-browser screenshot` per shell call captures whatever state the
#    page happened to be in — which is how you end up with duplicate PNGs and
#    no match-results shot at all. So the whole flow runs in one script.
#
# 2. `agent-browser screenshot` returns before the PNG is on disk. If you
#    change the page immediately afterwards, the file that lands is the NEXT
#    screen and every shot is silently off by one. `shot()` waits for the file
#    to appear and its size to stop changing before returning.
#
# 3. Even with (2), a queued capture can still land after a later navigation.
#    So each screen is captured from a FRESH page state: navigate, log in,
#    reach the target view, shoot, and only then move on. The page cannot
#    change underneath a capture that is still in flight.
#
# Usage:  ./scripts/capture.sh [base_url] [out_dir]
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
OUT="${2:-/tmp/nabz-shots}"

rm -rf "$OUT" && mkdir -p "$OUT"

shot() {
  local path="$1"
  agent-browser screenshot "$path" >/dev/null
  local prev=-1 size=-1
  for _ in $(seq 1 40); do
    if [ -f "$path" ]; then
      size=$(stat -c %s "$path" 2>/dev/null || echo -1)
      if [ "$size" = "$prev" ] && [ "$size" -gt 0 ]; then
        sleep 1
        return 0
      fi
      prev="$size"
    fi
    sleep 0.25
  done
  echo "screenshot never stabilised: $path" >&2
  return 1
}

# Land on a clean login screen (a stale token would skip it entirely).
reset_to_login() {
  agent-browser open "$BASE" >/dev/null
  sleep 2
  agent-browser eval "localStorage.clear(); 1" >/dev/null
  agent-browser reload >/dev/null
  sleep 2
}

login() {
  agent-browser eval "document.getElementById('login-form').requestSubmit(); 1" >/dev/null
  sleep 4
}

select_first_patient() {
  # The list renders after the login round-trip; wait for it rather than
  # assuming a fixed sleep was long enough.
  for _ in $(seq 1 20); do
    if [ "$(agent-browser get count '.patient-item' | tail -1)" = "10" ]; then
      break
    fi
    sleep 0.5
  done
  agent-browser eval "document.querySelector('.patient-item[data-id]').click(); 1" >/dev/null
  sleep 4
}

agent-browser set viewport 1440 900 >/dev/null

# 1 — login
reset_to_login
agent-browser is visible "#login-form" | grep -qi true
shot "$OUT/01-login.png"

# 2 — patient list
reset_to_login
login
[ "$(agent-browser get count '.patient-item' | tail -1)" = "10" ]
shot "$OUT/02-patients.png"

# 3 — patient detail: molecular profile, no run yet
reset_to_login
login
select_first_patient
agent-browser get text '.detail-pane' | grep -q 'Molecular findings'
agent-browser get text '.detail-pane' | grep -q 'No match run yet'
shot "$OUT/03-patient-detail.png"

# 4 — match results: all twelve verdicts, nothing dropped
reset_to_login
login
select_first_patient
agent-browser eval "document.getElementById('run-match-btn').click(); 1" >/dev/null
sleep 5
[ "$(agent-browser get count '.match-card' | tail -1)" = "12" ]
shot "$OUT/04-match-results.png"

# 5 — cohort
reset_to_login
login
agent-browser eval "document.querySelector('[data-view=\"cohort\"]').click(); 1" >/dev/null
sleep 4
agent-browser get text '#view-cohort' | grep -q 'Cohort overview'
shot "$OUT/05-cohort.png"

# 6 — catalogue
reset_to_login
login
agent-browser eval "document.querySelector('[data-view=\"catalogue\"]').click(); 1" >/dev/null
sleep 4
agent-browser get text '#view-catalogue' | grep -q 'Therapy catalogue'
shot "$OUT/06-catalogue.png"

# 7 — mobile, on the patient workspace
reset_to_login
login
select_first_patient
agent-browser set viewport 390 844 >/dev/null
sleep 3
OVERFLOW="$(agent-browser eval "document.documentElement.scrollWidth + '/' + document.documentElement.clientWidth" | tr -d '"')"
echo "mobile width $OVERFLOW"
[ "${OVERFLOW%%/*}" = "${OVERFLOW##*/}" ]
shot "$OUT/07-mobile.png"

echo "--- captured ---"
md5sum "$OUT"/*.png
echo "--- unique hashes (want 7) ---"
md5sum "$OUT"/*.png | awk '{print $1}' | sort -u | wc -l
