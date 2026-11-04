/* Nabz — front-end. Vanilla JS, no build step.
   State lives in one object; every render is a pure function of it. */

(() => {
  'use strict';

  const API = '';
  const TOKEN_KEY = 'nabz.token';

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || null,
    user: null,
    patients: [],
    selectedId: null,
    detail: null,
    run: null,
    therapies: [],
    cohort: null,
    filter: '',
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  /* ───────────────────────── helpers ───────────────────────── */

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function toast(message, isError = false) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.toggle('error', isError);
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 3600);
  }

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const response = await fetch(API + path, { ...options, headers });

    if (response.status === 401 && state.token) {
      signOut();
      throw new Error('Session expired. Please sign in again.');
    }
    if (response.status === 204) return null;

    const text = await response.text();
    let body = null;
    if (text) {
      try { body = JSON.parse(text); } catch { body = { detail: text }; }
    }
    if (!response.ok) {
      const detail = body && body.detail;
      const message = Array.isArray(detail)
        ? detail.map((d) => d.msg || d).join('; ')
        : detail || `Request failed (${response.status})`;
      throw new Error(message);
    }
    return body;
  }

  /* ───────────────────────── auth ───────────────────────── */

  function showAuth() {
    $('#auth-screen').hidden = false;
    $('#app').hidden = true;
  }

  function showApp() {
    $('#auth-screen').hidden = true;
    $('#app').hidden = false;
    $('#user-chip').textContent = state.user ? state.user.full_name : '';
  }

  function signOut() {
    state.token = null;
    state.user = null;
    state.patients = [];
    state.selectedId = null;
    state.detail = null;
    localStorage.removeItem(TOKEN_KEY);
    showAuth();
  }

  async function signIn(email, password) {
    const button = $('#login-btn');
    const errorEl = $('#auth-error');
    errorEl.hidden = true;
    button.disabled = true;
    button.textContent = 'Signing in…';

    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem(TOKEN_KEY, state.token);
      showApp();
      await loadPatients();
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = 'Sign in';
    }
  }

  /* ───────────────────────── patients ───────────────────────── */

  async function loadPatients() {
    try {
      state.patients = await api('/api/patients?limit=200');
      renderPatientList();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function renderPatientList() {
    const list = $('#patient-list');
    const filter = state.filter.trim().toLowerCase();
    const rows = filter
      ? state.patients.filter((p) => p.diagnosis.toLowerCase().includes(filter))
      : state.patients;

    $('#patient-count').textContent = `${rows.length}/${state.patients.length}`;

    if (!rows.length) {
      list.innerHTML = '<li class="patient-item"><div class="pi-meta">No patients match.</div></li>';
      return;
    }

    list.innerHTML = rows.map((p) => `
      <li class="patient-item ${p.id === state.selectedId ? 'active' : ''}" data-id="${p.id}">
        <div class="pi-name">${esc(p.display_name)}</div>
        <div class="pi-meta">${esc(p.diagnosis)} · Stage ${esc(p.stage)}</div>
        <div class="pi-mrn">${esc(p.mrn)} · ${p.variants.length} variant${p.variants.length === 1 ? '' : 's'}</div>
      </li>
    `).join('');

    list.querySelectorAll('.patient-item[data-id]').forEach((el) => {
      el.addEventListener('click', () => selectPatient(Number(el.dataset.id)));
    });
  }

  async function selectPatient(id) {
    state.selectedId = id;
    state.run = null;
    renderPatientList();
    $('#detail-empty').hidden = true;
    $('#detail-content').hidden = false;
    $('#detail-content').innerHTML = '<p class="muted">Loading…</p>';

    try {
      const [patient, runs] = await Promise.all([
        api(`/api/patients/${id}`),
        api(`/api/patients/${id}/matches`),
      ]);
      state.detail = patient;
      state.run = runs && runs.length ? runs[0] : null;
      renderDetail();
    } catch (err) {
      $('#detail-content').innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    }
  }

  function renderDetail() {
    const p = state.detail;
    if (!p) return;

    const variants = p.variants || [];
    const run = state.run;

    const variantRows = variants.length
      ? variants.map((v) => `
          <tr>
            <td class="mono">${esc(v.gene)}</td>
            <td class="mono">${esc(v.protein_change)}</td>
            <td class="mono">${v.variant_type}</td>
            <td class="mono">${v.variant_type === 'msi' || v.variant_type === 'fusion' || v.variant_type === 'cnv' ? '—' : (v.vaf * 100).toFixed(1) + '%'}</td>
            <td><span class="pill pill-${esc(v.classification)}">${esc(v.classification.replace(/_/g, ' '))}</span></td>
          </tr>`).join('')
      : '<tr><td colspan="5" class="muted">No molecular findings recorded.</td></tr>';

    const matchBlock = run
      ? renderMatches(run)
      : `<div class="empty-state" style="padding:2rem 1rem">
           <h3>No match run yet</h3>
           <p>Run the matcher to see which therapies this profile reaches.</p>
         </div>`;

    $('#detail-content').innerHTML = `
      <div class="detail-head">
        <div>
          <h2>${esc(p.display_name)}</h2>
          <div class="detail-sub">${esc(p.diagnosis)} · ${esc(p.mrn)}</div>
        </div>
        <button class="btn btn-accent" id="run-match-btn">Run matcher</button>
      </div>

      <div class="meta-grid">
        <div class="meta-cell"><div class="mc-label">Age</div><div class="mc-value">${p.age}</div></div>
        <div class="meta-cell"><div class="mc-label">Sex</div><div class="mc-value">${esc(p.sex)}</div></div>
        <div class="meta-cell"><div class="mc-label">Stage</div><div class="mc-value">${esc(p.stage)}</div></div>
        <div class="meta-cell"><div class="mc-label">ECOG</div><div class="mc-value">${p.ecog}</div></div>
        <div class="meta-cell"><div class="mc-label">Prior lines</div><div class="mc-value">${p.prior_lines}</div></div>
        <div class="meta-cell"><div class="mc-label">Variants</div><div class="mc-value">${variants.length}</div></div>
      </div>

      <div class="block-title"><h3>Molecular findings</h3></div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Gene</th><th>Protein</th><th>Type</th><th>VAF</th><th>Class</th></tr></thead>
          <tbody>${variantRows}</tbody>
        </table>
      </div>

      <div class="block-title">
        <h3>Therapy matches</h3>
        ${run ? `<span class="muted">${run.actionable_count} eligible of ${run.candidate_count} considered</span>` : ''}
      </div>
      ${matchBlock}
    `;

    const btn = $('#run-match-btn');
    if (btn) btn.addEventListener('click', () => runMatcher(p.id));
  }

  function renderMatches(run) {
    const order = { eligible: 0, blocked: 1, not_applicable: 2 };
    const sorted = [...run.matches].sort((a, b) => {
      const s = (order[a.status] ?? 9) - (order[b.status] ?? 9);
      if (s !== 0) return s;
      return (a.tier ?? 99) - (b.tier ?? 99) || b.score - a.score;
    });

    return `<div class="match-list">${sorted.map((m) => `
      <div class="match-card ${esc(m.status)}">
        <div class="match-top">
          <span class="match-name">${esc(m.therapy_name)}</span>
          <span class="match-modality">${esc(m.modality)}</span>
          ${m.tier ? `<span class="pill pill-tier">Tier ${m.tier}</span>` : ''}
          <span class="pill pill-${esc(m.status)}">${esc(m.status.replace(/_/g, ' '))}</span>
          <span class="match-score">${m.score.toFixed(3)}</span>
        </div>
        <p class="match-rationale">${esc(m.rationale)}</p>
        ${m.blockers && m.blockers.length
          ? `<ul class="match-blockers">${m.blockers.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>`
          : ''}
        ${m.matched_variants && m.matched_variants.length
          ? `<div class="match-variants">matched: ${m.matched_variants.map(esc).join(' · ')}</div>`
          : ''}
      </div>
    `).join('')}</div>`;
  }

  async function runMatcher(patientId) {
    const btn = $('#run-match-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Matching…'; }
    try {
      state.run = await api(`/api/patients/${patientId}/match`, { method: 'POST' });
      renderDetail();
      toast(`Matcher ran — ${state.run.actionable_count} eligible therapies.`);
    } catch (err) {
      toast(err.message, true);
      if (btn) { btn.disabled = false; btn.textContent = 'Run matcher'; }
    }
  }

  /* ───────────────────────── cohort ───────────────────────── */

  async function loadCohort() {
    try {
      state.cohort = await api('/api/analytics/cohort');
      renderCohort();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function bars(container, data, unit = '') {
    const entries = Object.entries(data || {});
    if (!entries.length) {
      container.innerHTML = '<p class="muted">No data yet.</p>';
      return;
    }
    const max = Math.max(...entries.map(([, v]) => v), 1);
    container.innerHTML = entries.map(([label, value]) => `
      <div class="bar-row">
        <span class="bar-label" title="${esc(label)}">${esc(label)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${(value / max) * 100}%"></span></span>
        <span class="bar-value">${value}${unit}</span>
      </div>
    `).join('');
  }

  function renderCohort() {
    const c = state.cohort;
    if (!c) return;

    $('#cohort-stats').innerHTML = `
      <div class="stat">
        <div class="s-label">Patients</div>
        <div class="s-value">${c.patient_count}</div>
        <div class="s-note">in your cohort</div>
      </div>
      <div class="stat">
        <div class="s-label">With actionable variant</div>
        <div class="s-value">${c.patients_with_actionable_variant}</div>
        <div class="s-note">${(c.actionable_rate * 100).toFixed(0)}% of cohort</div>
      </div>
      <div class="stat">
        <div class="s-label">Genes tested</div>
        <div class="s-value">${c.genes_tested.length}</div>
        <div class="s-note">distinct loci</div>
      </div>
      <div class="stat">
        <div class="s-label">Diagnoses</div>
        <div class="s-value">${Object.keys(c.by_diagnosis).length}</div>
        <div class="s-note">distinct tumour types</div>
      </div>
    `;

    bars($('#gene-bars'), c.actionable_variant_counts);
    bars($('#diagnosis-bars'), c.by_diagnosis);
    bars($('#stage-bars'), c.by_stage);

    $('#genes-tested').innerHTML = c.genes_tested.length
      ? c.genes_tested.map((g) => `<span class="chip">${esc(g)}</span>`).join('')
      : '<p class="muted">No genes recorded.</p>';
  }

  /* ───────────────────────── catalogue ───────────────────────── */

  async function loadCatalogue() {
    try {
      state.therapies = await api('/api/therapies');
      renderCatalogue();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function renderCatalogue() {
    const tbody = $('#catalogue-table tbody');
    if (!state.therapies.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted">Catalogue is empty.</td></tr>';
      return;
    }
    tbody.innerHTML = state.therapies.map((t) => `
      <tr>
        <td><strong>${esc(t.name)}</strong></td>
        <td>${esc(t.modality)}</td>
        <td class="mono">${esc(t.biomarker_gene)}</td>
        <td>${esc(t.requirement)}</td>
        <td><span class="pill pill-tier">${esc(t.evidence_level)}</span></td>
        <td>${esc(t.approval_status)}</td>
        <td class="mono">${t.line_of_therapy}</td>
      </tr>
    `).join('');
  }

  /* ───────────────────────── navigation ───────────────────────── */

  function switchView(name) {
    $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === name));
    $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${name}`));
    if (name === 'cohort') loadCohort();
    if (name === 'catalogue') loadCatalogue();
  }

  /* ───────────────────────── boot ───────────────────────── */

  function bind() {
    $('#login-form').addEventListener('submit', (event) => {
      event.preventDefault();
      signIn($('#email').value.trim(), $('#password').value);
    });

    $('#logout-btn').addEventListener('click', signOut);

    $('#patient-search').addEventListener('input', (event) => {
      state.filter = event.target.value;
      renderPatientList();
    });

    $$('.tab').forEach((tab) => {
      tab.addEventListener('click', () => switchView(tab.dataset.view));
    });
  }

  async function boot() {
    bind();
    if (!state.token) { showAuth(); return; }

    try {
      state.user = await api('/api/auth/me');
      showApp();
      await loadPatients();
    } catch {
      signOut();
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
