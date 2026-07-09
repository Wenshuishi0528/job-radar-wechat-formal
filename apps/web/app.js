const $ = (id) => document.getElementById(id);

const state = {
  loading: false,
  opportunities: [],
  sortKey: 'updated_at',
  sortDirection: 'desc',
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[ch]));
}

function formatDate(value, fallback = '未知') {
  if (!value) return fallback;
  const match = String(value).match(/^\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : String(value);
}

function degreeLabel(value) {
  return {
    associate: '专科', bachelor: '本科', master: '硕士', phd: '博士',
  }[value] || '学历未注明';
}

function statusLabel(value) {
  return {
    open: '开放', closing_soon: '即将截止', pending_review: '待确认',
    closed: '已截止', expired: '已截止',
  }[value] || '待确认';
}

function statusClass(value) {
  if (value === 'open') return 'good';
  if (value === 'closed' || value === 'expired') return 'bad';
  return 'warn';
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `请求失败：${response.status}`);
  return data;
}

function searchParams() {
  const params = new URLSearchParams();
  const values = {
    query: $('query').value.trim(),
    city: $('city').value.trim(),
    cohort: $('cohort').value.trim(),
    recruitment_type: $('recruitmentType').value,
    company_type: $('companyType').value,
    industry: $('industry').value,
    source_level: $('sourceLevel').value,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  params.set('include_expired', String($('includeExpired').checked));
  params.set('limit', '500');
  return params;
}

function refreshBody() {
  return {
    keyword: $('query').value.trim(),
    provider: $('searchProvider').value,
    source_scope: $('sourceScope').value,
    freshness_days: Number($('freshnessDays').value || 90),
    max_results: Number($('maxResults').value || 50),
  };
}

function setSearchStatus(message, type = '') {
  const element = $('searchStatus');
  element.textContent = message;
  element.className = `search-status ${type}`.trim();
}

function setLoading(loading) {
  state.loading = loading;
  $('searchButton').disabled = loading;
  $('searchButton').textContent = loading ? '正在搜索...' : '搜索并刷新';
}

function renderOpportunityRow(item) {
  const recordLabel = item.record_type === 'job' ? '具体岗位' : '招聘项目';
  const campaignLine = item.record_type === 'job' && item.campaign_name && item.campaign_name !== item.title
    ? `<span class="cell-sub">${escapeHtml(item.campaign_name)}</span>` : '';
  const companyMeta = [item.company_type, item.industry].filter((value) => value && value !== 'unknown').join(' · ') || '企业信息待补充';
  const cities = (item.cities || []).join(' / ') || '公告内查看';
  const deadline = item.deadline ? formatDate(item.deadline) : '未注明';
  const sourceLevel = String(item.source_level || 'C').toLowerCase();
  const sourceName = item.source_domain || '来源待确认';
  const status = `<span class="tag ${statusClass(item.status)}">${statusLabel(item.status)}</span>`;
  const matchTag = item.match
    ? `<span class="tag ${item.match.status === 'eligible' ? 'good' : item.match.status === 'not_eligible' ? 'bad' : 'warn'}">匹配 ${Math.round((item.match.score || 0) * 100)}%</span>` : '';
  const applyUrl = item.apply_url || '';
  const sourceUrl = item.source_url || '';
  const applyAction = applyUrl
    ? `<a class="primary-link" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener">${sourceUrl && sourceUrl !== applyUrl ? '官网 / 投递' : '查看'}</a>` : '';
  const sourceAction = sourceUrl && sourceUrl !== applyUrl
    ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">公告</a>` : '';
  const detailAction = item.job_id
    ? `<button type="button" data-job-id="${Number(item.job_id)}">证据</button>` : '';
  const batch = [item.target_cohort || '届别未注明', item.recruitment_type || '类型未注明'].join(' · ');
  return `<tr>
    <td data-label="更新"><span class="cell-main">${escapeHtml(formatDate(item.updated_at))}</span><span class="cell-sub">${status}</span></td>
    <td data-label="公司"><span class="cell-main">${escapeHtml(item.company_name)}</span><span class="cell-sub">${escapeHtml(companyMeta)}</span></td>
    <td data-label="岗位 / 项目"><div class="title-line"><span class="cell-main">${escapeHtml(item.title)}</span><span class="tag">${recordLabel}</span>${matchTag}</div>${campaignLine}<span class="cell-sub">${escapeHtml(degreeLabel(item.degree_min))}</span></td>
    <td data-label="批次"><span class="cell-main">${escapeHtml(batch)}</span></td>
    <td data-label="地点"><span class="cell-main">${escapeHtml(cities)}</span></td>
    <td data-label="截止"><span class="cell-main ${item.status === 'closed' ? 'deadline-passed' : ''}">${escapeHtml(deadline)}</span></td>
    <td data-label="来源"><span class="tag source-${sourceLevel}">来源 ${escapeHtml(item.source_level || 'C')}</span><span class="cell-sub">${escapeHtml(sourceName)}</span></td>
    <td data-label="操作"><div class="row-actions">${applyAction}${sourceAction}${detailAction}</div></td>
  </tr>`;
}

function bindDetailButtons() {
  document.querySelectorAll('[data-job-id]').forEach((button) => {
    button.addEventListener('click', () => showDetail(Number(button.dataset.jobId)));
  });
}

function sortedOpportunities(items) {
  const sourceRanks = { S: 4, A: 3, B: 2, C: 1, D: 0 };
  const direction = state.sortDirection === 'asc' ? 1 : -1;
  return [...items].sort((left, right) => {
    let a = left[state.sortKey] ?? '';
    let b = right[state.sortKey] ?? '';
    if (state.sortKey === 'source_level') {
      a = sourceRanks[a] || 0;
      b = sourceRanks[b] || 0;
    }
    return String(a).localeCompare(String(b), 'zh-CN', { numeric: true }) * direction;
  });
}

function updateSortHeaders() {
  document.querySelectorAll('[data-sort-column]').forEach((header) => {
    if (header.dataset.sortColumn === state.sortKey) header.setAttribute('aria-sort', state.sortDirection === 'asc' ? 'ascending' : 'descending');
    else header.removeAttribute('aria-sort');
  });
}

function renderOpportunities(items) {
  state.opportunities = items;
  const sorted = sortedOpportunities(items);
  $('opportunityRows').innerHTML = sorted.map(renderOpportunityRow).join('');
  $('emptyOpportunities').hidden = items.length > 0;
  document.querySelector('.opportunity-table')?.classList.toggle('empty', items.length === 0);
  updateSortHeaders();
  bindDetailButtons();
}

async function loadOpportunities() {
  const data = await fetchJson(`/api/opportunities?${searchParams().toString()}`);
  renderOpportunities(data.items || []);
  $('resultSummary').textContent = `共 ${data.count || 0} 条 · ${data.job_count || 0} 个具体岗位 · ${data.campaign_count || 0} 个招聘项目`;
  return data;
}

async function runSearch({ refresh = true } = {}) {
  if (state.loading) return;
  setLoading(true);
  let localData = null;
  try {
    setSearchStatus('正在读取本地机会库...');
    localData = await loadOpportunities();
    switchView('opportunities');
  } catch (error) {
    setSearchStatus(error.message, 'error');
    setLoading(false);
    return;
  }
  const body = refreshBody();
  if (!refresh || !$('onlineRefresh').checked || !body.keyword) {
    setSearchStatus(`已显示 ${localData.count || 0} 条本地结果`, 'success');
    setLoading(false);
    return;
  }
  try {
    setSearchStatus(`已显示 ${localData.count || 0} 条本地结果，正在联网更新...`);
    const result = await fetchJson('/api/jobs/auto-search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const updated = await loadOpportunities();
    const imported = result.opportunities_imported || 0;
    const failures = (result.providers || []).filter((provider) => provider.error).map((provider) => provider.provider).join('、');
    const suffix = failures ? `；${failures} 暂不可用` : '';
    setSearchStatus(`更新完成：本次整理 ${imported} 条，当前匹配 ${updated.count || 0} 条${suffix}`, 'success');
    localStorage.setItem('jobRadarLastRefreshDate', new Date().toISOString().slice(0, 10));
  } catch (error) {
    setSearchStatus(`本地结果已显示；联网更新失败：${error.message}`, 'error');
  } finally {
    setLoading(false);
  }
}

function profile() {
  const max = $('maxWrittenBurden').value;
  return {
    graduation_date: $('graduationDate').value || null,
    school_region: $('schoolRegion').value,
    degree: $('degree').value,
    target_cities: $('targetCities').value.split(',').map((value) => value.trim()).filter(Boolean),
    max_written_test_burden: max === '' ? null : Number(max),
  };
}

function matchedOpportunity(item) {
  const job = item.job;
  return {
    id: `job-${job.id}`,
    record_type: 'job',
    job_id: job.id,
    campaign_id: job.campaign?.id,
    updated_at: job.last_verified_at,
    company_name: job.company?.name || '未知公司',
    company_type: job.company?.company_type || 'unknown',
    industry: job.company?.industry || 'unknown',
    title: job.title,
    campaign_name: job.campaign?.name || '',
    recruitment_type: job.campaign?.recruitment_type,
    target_cohort: job.campaign?.target_cohort,
    cities: job.cities || [],
    degree_min: job.degree_min,
    deadline: job.campaign?.deadline,
    status: job.status,
    apply_url: job.apply_url,
    source_url: job.source_url,
    source_domain: job.source_url ? new URL(job.source_url).hostname : '',
    source_level: job.source_level,
    quality_score: job.quality_score,
    risk_level: job.risk_level,
    match: item.match,
  };
}

async function runMatch() {
  setSearchStatus('正在按画像匹配具体岗位...');
  try {
    const filters = Object.fromEntries(searchParams().entries());
    delete filters.include_expired;
    delete filters.limit;
    const data = await fetchJson('/api/match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: profile(), filters }),
    });
    const items = (data.items || []).map(matchedOpportunity);
    renderOpportunities(items);
    $('resultSummary').textContent = `共 ${items.length} 个具体岗位，已按画像判断`;
    setSearchStatus(`画像匹配完成：${items.length} 个具体岗位`, 'success');
    switchView('opportunities');
  } catch (error) {
    setSearchStatus(error.message, 'error');
  }
}

async function showDetail(jobId) {
  try {
    const job = await fetchJson(`/api/jobs/${jobId}`);
    const evidence = (job.evidence || []).map((entry) => `<li><strong>${escapeHtml(entry.field_name)}</strong>：${escapeHtml(entry.value_text || '')}<br><span class="cell-sub">${escapeHtml(entry.evidence_text || '')}</span></li>`).join('');
    const changes = (job.changes || []).map((entry) => `<li>${escapeHtml(formatDate(entry.detected_at))}：${escapeHtml(entry.field_name)}从 ${escapeHtml(entry.old_value || '空')} 改为 ${escapeHtml(entry.new_value || '空')}</li>`).join('');
    $('detailContent').innerHTML = `<h3>${escapeHtml(job.title)}</h3>
      <p>${escapeHtml(job.company?.name || '')} · ${escapeHtml(job.campaign?.name || '')}</p>
      <h3>流程</h3><p>${escapeHtml(job.process_rule?.process_text || '公告未注明')}</p>
      <h3>来源证据</h3><ul>${evidence || '<li>暂无岗位级证据，请打开公告核对。</li>'}</ul>
      <h3>变化记录</h3><ul>${changes || '<li>暂无变化记录。</li>'}</ul>`;
    $('detailDialog').showModal();
  } catch (error) {
    setSearchStatus(error.message, 'error');
  }
}

async function importText() {
  const text = $('importText').value.trim();
  const company = $('importCompany').value.trim();
  if (!company || text.length < 20) {
    $('importStatus').textContent = '请填写公司和至少 20 个字的公告正文。';
    return;
  }
  try {
    await fetchJson('/api/admin/import-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_name: company,
        job_title: $('importTitle').value.trim() || '招聘项目',
        source_url: $('importUrl').value.trim() || null,
        source_level: 'C',
        text,
      }),
    });
    $('importStatus').textContent = '已解析并加入机会库。';
    await loadOpportunities();
  } catch (error) {
    $('importStatus').textContent = error.message;
  }
}

function articleParams() {
  const params = new URLSearchParams();
  const query = $('articleQuery').value.trim();
  if (query) params.set('q', query);
  params.set('freshness_days', $('articleFreshness').value || '90');
  params.set('trusted_only', 'false');
  params.set('limit', '100');
  return params;
}

function renderArticle(item) {
  const link = item.canonical_url ? `<a href="${escapeHtml(item.canonical_url)}" target="_blank" rel="noopener">查看原文</a>` : '';
  return `<article class="article-row">
    <h3>${escapeHtml(item.title)}</h3>
    <div class="article-meta"><span class="tag">${escapeHtml(item.account_name || '公众号未知')}</span><span class="tag source-${String(item.source_level || 'C').toLowerCase()}">来源 ${escapeHtml(item.source_level || 'C')}</span><span class="tag ${item.is_stale ? 'warn' : 'good'}">${item.is_stale ? '可能过期' : '新鲜'}</span></div>
    <p>${escapeHtml(item.digest || (item.content_text || '').slice(0, 180))}</p>
    <p>${escapeHtml(formatDate(item.publish_at, '发布时间未知'))} · ${link}</p>
  </article>`;
}

async function loadArticles() {
  try {
    const data = await fetchJson(`/api/wechat/articles?${articleParams().toString()}`);
    $('articleRows').innerHTML = (data.items || []).map(renderArticle).join('') || '<div class="empty-state"><h3>暂无匹配公众号文章</h3><p>可切换搜狗微信通道后执行联网更新。</p></div>';
  } catch (error) {
    $('articleRows').innerHTML = `<div class="empty-state"><h3>文章读取失败</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function switchView(name) {
  document.querySelectorAll('.view-tab').forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  const opportunitiesActive = name === 'opportunities';
  $('opportunitiesView').classList.toggle('active', opportunitiesActive);
  $('opportunitiesView').hidden = !opportunitiesActive;
  $('articlesView').classList.toggle('active', !opportunitiesActive);
  $('articlesView').hidden = opportunitiesActive;
  if (!opportunitiesActive) loadArticles();
}

function clearPresetState() {
  document.querySelectorAll('[data-preset]').forEach((button) => button.classList.remove('active'));
}

function resetFilters() {
  $('query').value = '';
  $('city').value = '';
  $('cohort').value = '';
  $('recruitmentType').value = '';
  $('companyType').value = '';
  $('industry').value = '';
  $('sourceLevel').value = 'B';
  $('includeExpired').checked = false;
  clearPresetState();
}

async function applyPreset(name, button) {
  resetFilters();
  button.classList.add('active');
  const campusYear = new Date().getMonth() + 1 >= 6 ? new Date().getFullYear() + 1 : new Date().getFullYear();
  if (name === 'latest') {
    $('query').value = '校园招聘';
    $('freshnessDays').value = '1';
  } else if (name === 'autumn') {
    $('query').value = '秋招';
    $('cohort').value = String(campusYear);
    $('freshnessDays').value = '90';
  } else if (name === 'soe') {
    $('query').value = '校园招聘';
    $('companyType').value = '国央企';
  } else if (name === 'intern') {
    $('query').value = '实习';
    $('recruitmentType').value = '实习';
  } else if (name === 'all') {
    await runSearch({ refresh: false });
    return;
  }
  await runSearch({ refresh: true });
}

async function openExternalSearch(provider) {
  const keyword = $('query').value.trim() || '秋招';
  const popup = window.open('about:blank', '_blank');
  if (popup) popup.opener = null;
  try {
    const data = await fetchJson(`/api/wechat/search-links?keyword=${encodeURIComponent(keyword)}&freshness_days=${encodeURIComponent($('freshnessDays').value)}&source_scope=${encodeURIComponent($('sourceScope').value)}`);
    const url = data.urls?.[provider];
    if (!url) throw new Error('没有生成搜索链接');
    if (popup) popup.location.href = url;
    else window.location.href = url;
  } catch (error) {
    if (popup) popup.close();
    setSearchStatus(error.message, 'error');
  }
}

async function loadStatus() {
  try {
    const [config, registry] = await Promise.all([
      fetchJson('/api/wechat/config'),
      fetchJson('/api/sources/registry'),
    ]);
    $('modeStatus').textContent = config.personal_mode ? '个人本地模式' : '本地模式';
    $('modeStatus').classList.toggle('good', config.personal_mode);
    $('registryStatus').textContent = `${registry.count || 0} 个正式来源`;
    $('registryStatus').classList.add('good');
    $('networkStatus').textContent = config.web_search_import_enabled ? '联网更新已开启' : '联网更新未开启';
    $('networkStatus').classList.toggle('good', config.web_search_import_enabled);
    $('networkStatus').classList.toggle('warn', !config.web_search_import_enabled);
  } catch (error) {
    $('networkStatus').textContent = '状态读取失败';
    $('networkStatus').classList.add('warn');
  }
}

function setLeftWidth(width) {
  const workspace = $('workspace');
  const min = 310;
  const max = Math.min(640, workspace.getBoundingClientRect().width - 460);
  const next = Math.max(min, Math.min(max, width));
  workspace.style.setProperty('--left-width', `${Math.round(next)}px`);
  $('splitter').setAttribute('aria-valuenow', String(Math.round(next)));
  localStorage.setItem('jobRadarLeftWidth', `${Math.round(next)}px`);
}

function initSplitter() {
  const workspace = $('workspace');
  const splitter = $('splitter');
  const saved = Number.parseInt(localStorage.getItem('jobRadarLeftWidth') || '', 10);
  if (Number.isFinite(saved)) setLeftWidth(saved);
  let dragging = false;
  splitter.addEventListener('pointerdown', (event) => {
    dragging = true;
    splitter.setPointerCapture(event.pointerId);
    document.body.classList.add('is-resizing');
  });
  splitter.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    setLeftWidth(event.clientX - workspace.getBoundingClientRect().left);
  });
  const stop = () => {
    dragging = false;
    document.body.classList.remove('is-resizing');
  };
  splitter.addEventListener('pointerup', stop);
  splitter.addEventListener('pointercancel', stop);
  splitter.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const current = Number.parseInt(getComputedStyle(workspace).getPropertyValue('--left-width'), 10) || 380;
    setLeftWidth(current + (event.key === 'ArrowRight' ? 20 : -20));
  });
}

function bindEvents() {
  $('searchForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    clearPresetState();
    await runSearch({ refresh: true });
  });
  $('resetFilters').addEventListener('click', async () => {
    resetFilters();
    await runSearch({ refresh: false });
  });
  $('runMatch').addEventListener('click', runMatch);
  $('importButton').addEventListener('click', importText);
  $('closeDialog').addEventListener('click', () => $('detailDialog').close());
  $('searchArticles').addEventListener('click', loadArticles);
  $('openGoogle').addEventListener('click', () => openExternalSearch('google'));
  $('openBing').addEventListener('click', () => openExternalSearch('bing'));
  $('openSogou').addEventListener('click', () => openExternalSearch('sogou'));
  document.querySelectorAll('.view-tab').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
  document.querySelectorAll('[data-preset]').forEach((button) => button.addEventListener('click', () => applyPreset(button.dataset.preset, button)));
  document.querySelectorAll('[data-sort]').forEach((button) => button.addEventListener('click', () => {
    const key = button.dataset.sort;
    if (state.sortKey === key) state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
    else {
      state.sortKey = key;
      state.sortDirection = key === 'updated_at' || key === 'deadline' || key === 'source_level' ? 'desc' : 'asc';
    }
    renderOpportunities(state.opportunities);
  }));
}

async function init() {
  const campusYear = new Date().getMonth() + 1 >= 6 ? new Date().getFullYear() + 1 : new Date().getFullYear();
  $('autumnPreset').textContent = `${String(campusYear).slice(-2)}届热门秋招`;
  initSplitter();
  bindEvents();
  loadStatus();
  loadArticles();
  const today = new Date().toISOString().slice(0, 10);
  const shouldRefresh = localStorage.getItem('jobRadarLastRefreshDate') !== today;
  await runSearch({ refresh: shouldRefresh });
}

init();
