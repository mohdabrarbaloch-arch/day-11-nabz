#!/bin/bash
# Deterministic screenshot capture at a fixed desktop viewport.
#
# Traps this script works around, all observed:
#  - a plain .click() on the submit button does not fire the form handler under
#    CDP, so requestSubmit() is used
#  - #run-match-btn only exists after a patient is selected
#  - `set viewport` reloads the page, so it is called ONCE at the start, never
#    inside shot() (doing so silently re-captured the login screen)
#  - every step waits on a real DOM predicate instead of a fixed sleep
set -u
cd /workspace/project-day-11-nabz
rm -f screenshots/*.png

shot() { agent-browser screenshot "screenshots/$1" >/dev/null 2>&1 && echo "  saved $1"; }
waitfor() {
  local expr="$1" n="${2:-25}" i=0
  while [ $i -lt "$n" ]; do
    [ "$(agent-browser eval "$expr" 2>/dev/null | tr -d '"')" = "true" ] && return 0
    sleep 1; i=$((i+1))
  done
  echo "  TIMEOUT: $expr"; return 1
}

agent-browser set viewport 1440 900 >/dev/null 2>&1
agent-browser eval 'localStorage.clear(); "c"' >/dev/null 2>&1
agent-browser open http://127.0.0.1:8000 >/dev/null 2>&1
waitfor '!!document.getElementById("login-form")' && echo "  login ready"
shot 01-login.png

agent-browser eval 'document.getElementById("login-form").requestSubmit(); "in"' >/dev/null 2>&1
waitfor 'document.querySelectorAll(".patient-item").length===10' && echo "  list ready"
shot 02-patients.png

agent-browser eval 'document.querySelector(".patient-item[data-id=\"1\"]").click(); "sel"' >/dev/null 2>&1
waitfor 'document.querySelector(".detail-head h2")?.innerText==="Patient A. Rahman"' && echo "  detail ready"
shot 03-patient-detail.png

agent-browser eval 'document.getElementById("run-match-btn").click(); "ran"' >/dev/null 2>&1
waitfor 'document.querySelectorAll(".match-card").length===12' 30 && echo "  cards ready"
agent-browser eval 'var h=[...document.querySelectorAll(".block-title h3")].find(x=>/therapy matches/i.test(x.innerText)); h&&window.scrollTo(0,h.getBoundingClientRect().top+window.scrollY-70); "s"' >/dev/null 2>&1
# The success toast lives 3.6s and would sit on top of the cards.
sleep 5
shot 04-match-results.png

agent-browser eval 'var t=[...document.querySelectorAll(".tab")].find(x=>/cohort/i.test(x.innerText)); t&&t.click(); "c"' >/dev/null 2>&1
waitfor 'document.querySelectorAll(".bar-fill").length>0' && echo "  cohort ready"
sleep 1
shot 05-cohort.png

agent-browser eval 'var t=[...document.querySelectorAll(".tab")].find(x=>/catalogue/i.test(x.innerText)); t&&t.click(); "k"' >/dev/null 2>&1
waitfor 'document.querySelectorAll("#catalogue-table tbody tr").length===12' && echo "  catalogue ready"
sleep 1
shot 06-catalogue.png

echo "--- verify ---"
python3 - <<'PY'
from PIL import Image
import glob, hashlib
seen = {}
for f in sorted(glob.glob('screenshots/*.png')):
    h = hashlib.md5(open(f,'rb').read()).hexdigest()[:8]
    print(f"  {f} {Image.open(f).size} {h}")
    if h in seen: print(f"  !! DUPLICATE of {seen[h]}")
    seen[h] = f
print(f"  {len(seen)}/6 unique")
PY
