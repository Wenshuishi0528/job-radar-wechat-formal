const $ = (id) => document.getElementById(id);

const state = {
  loading: false,
  opportunities: [],
  clientItems: [],
  clientMode: false,
  currentView: 'opportunities',
  currentTrackerItem: null,
  page: 0,
  pageSize: 50,
  total: 0,
  sortKey: 'updated_at',
  sortDirection: 'desc',
};

const TRACKER_LABELS = {
  saved: '已收藏', preparing: '准备中', applied: '已投递', assessment: '测评 / 笔试',
  interview: '面试', offer: 'Offer', rejected: '未通过', withdrawn: '已放弃',
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

function trackerClass(value) {
  if (value === 'offer') return 'good';
  if (value === 'rejected' || value === 'withdrawn') return 'bad';
  if (value === 'applied' || value === 'assessment' || value === 'interview') return 'progress';
  return 'neutral';
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `请求失败：${response.status}`);
  return data;
}

function searchParams({ all = false, trackedOnly = null } = {}) {
  const params = new URLSearchParams();
  const values = {
    query: $('query').value.trim(),
    city: $('city').value.trim(),
    cohort: $('cohort').value.trim(),
    recruitment_type: $('recruitmentType').value,
    company_type: $('companyType').value,
    industry: $('industry').value,
    job_family: $('jobFamily').value,
    major: $('major').value.trim(),
    source_level: $('sourceLevel').value,
    tracker_status: $('trackerStatus').value,
    freshness_days: $('freshnessDays').value,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  params.set('include_expired', String($('includeExpired').checked));
  const onlyTracked = trackedOnly === null ? state.currentView === 'tracker' : trackedOnly;
  if (onlyTracked) params.set('tracked_only', 'true');
  params.set('offset', all ? '0' : String(state.page * state.pageSize));
  params.set('limit', all ? '500' : String(state.pageSize));
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
  const matchClass = item.match?.status === 'high' || item.match?.status === 'eligible'
    ? 'good' : item.match?.status === 'low' || item.match?.status === 'not_eligible' ? 'bad' : 'warn';
  const matchTag = item.match
    ? `<span class="tag ${matchClass}">匹配 ${Math.round((item.match.score || 0) * 100)}%</span>` : '';
  const applyUrl = item.apply_url || '';
  const sourceUrl = item.source_url || '';
  const applyAction = applyUrl
    ? `<a class="primary-link" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener">${sourceUrl && sourceUrl !== applyUrl ? '官网 / 投递' : '查看'}</a>` : '';
  const sourceAction = sourceUrl && sourceUrl !== applyUrl
    ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">公告</a>` : '';
  const detailAction = item.job_id
    ? `<button type="button" data-job-id="${Number(item.job_id)}">证据</button>` : '';
  const batch = [item.target_cohort || '届别未注明', item.recruitment_type || '类型未注明'].join(' · ');
  const directionTags = (item.job_families || []).slice(0, 2).map((value) => `<span class="tag">${escapeHtml(value)}</span>`).join('');
  const majorLine = (item.majors || []).length
    ? `<span class="cell-sub">专业：${escapeHtml(item.majors.slice(0, 4).join('、'))}</span>` : '';
  const trackerLabel = TRACKER_LABELS[item.tracker_status] || (item.is_favorite ? '已收藏' : '记录');
  const trackerButton = `<button type="button" class="tracker-button ${trackerClass(item.tracker_status)}" data-tracker-id="${escapeHtml(item.id)}">${escapeHtml(trackerLabel)}</button>`;
  return `<tr data-opportunity-id="${escapeHtml(item.id)}">
    <td data-label="更新"><span class="cell-main">${escapeHtml(formatDate(item.updated_at))}</span><span class="cell-sub">${status}</span></td>
    <td data-label="公司"><span class="cell-main">${escapeHtml(item.company_name)}</span><span class="cell-sub">${escapeHtml(companyMeta)}</span></td>
    <td data-label="岗位 / 项目"><div class="title-line"><span class="cell-main">${escapeHtml(item.title)}</span><span class="tag">${recordLabel}</span>${directionTags}${matchTag}</div>${campaignLine}<span class="cell-sub">${escapeHtml(degreeLabel(item.degree_min))}</span>${majorLine}</td>
    <td data-label="批次"><span class="cell-main">${escapeHtml(batch)}</span></td>
    <td data-label="地点"><span class="cell-main">${escapeHtml(cities)}</span></td>
    <td data-label="截止"><span class="cell-main ${item.status === 'closed' ? 'deadline-passed' : ''}">${escapeHtml(deadline)}</span></td>
    <td data-label="来源"><span class="tag source-${sourceLevel}">来源 ${escapeHtml(item.source_level || 'C')}</span><span class="cell-sub">${escapeHtml(sourceName)}</span></td>
    <td data-label="进展">${trackerButton}${item.next_action_at ? `<span class="cell-sub">下一步 ${escapeHtml(formatDate(item.next_action_at))}</span>` : ''}</td>
    <td data-label="操作"><div class="row-actions">${applyAction}${sourceAction}${detailAction}</div></td>
  </tr>`;
}

function bindRowButtons() {
  document.querySelectorAll('[data-job-id]').forEach((button) => {
    button.addEventListener('click', () => showDetail(Number(button.dataset.jobId)));
  });
  document.querySelectorAll('[data-tracker-id]').forEach((button) => {
    button.addEventListener('click', () => openTracker(button.dataset.trackerId));
  });
}

function sortedOpportunities(items) {
  const sourceRanks = { S: 4, A: 3, B: 2, C: 1, D: 0 };
  const direction = state.sortDirection === 'asc' ? 1 : -1;
  return [...items].sort((left, right) => {
    let a = left[state.sortKey] ?? '';
    let b = right[state.sortKey] ?? '';
    if (state.sortKey === 'match_score') {
      a = left.match?.score || 0;
      b = right.match?.score || 0;
    }
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

function paintOpportunities(items) {
  const sorted = sortedOpportunities(items);
  $('opportunityRows').innerHTML = sorted.map(renderOpportunityRow).join('');
  $('emptyOpportunities').hidden = items.length > 0;
  document.querySelector('.opportunity-table')?.classList.toggle('empty', items.length === 0);
  updateSortHeaders();
  bindRowButtons();
}

function updatePager() {
  const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  const visiblePage = Math.min(state.page + 1, pages);
  $('pagerSummary').textContent = `第 ${visiblePage} / ${pages} 页 · 共 ${state.total} 条`;
  $('previousPage').disabled = state.page <= 0;
  $('nextPage').disabled = state.page + 1 >= pages;
}

function renderOpportunities(items) {
  state.opportunities = items;
  paintOpportunities(items);
  updatePager();
}

function renderClientPage() {
  const sorted = sortedOpportunities(state.clientItems);
  const start = state.page * state.pageSize;
  state.opportunities = sorted.slice(start, start + state.pageSize);
  paintOpportunities(state.opportunities);
  updatePager();
}

async function loadOpportunities() {
  if (state.sortKey === 'match_score') {
    state.sortKey = 'updated_at';
    state.sortDirection = 'desc';
  }
  state.clientMode = false;
  state.clientItems = [];
  const data = await fetchJson(`/api/opportunities?${searchParams().toString()}`);
  state.total = data.count || 0;
  renderOpportunities(data.items || []);
  const viewLabel = state.currentView === 'tracker' ? '已记录机会' : '机会';
  $('resultSummary').textContent = `共 ${data.count || 0} 条${viewLabel} · ${data.job_count || 0} 个具体岗位 · ${data.campaign_count || 0} 个招聘项目`;
  return data;
}

async function runSearch({ refresh = true } = {}) {
  if (state.loading) return;
  setLoading(true);
  let localData = null;
  try {
    setSearchStatus('正在读取本地机会库...');
    localData = await loadOpportunities();
    switchView('opportunities', { load: false });
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

function splitValues(value) {
  return String(value || '').split(/[,，、\n]/).map((item) => item.trim()).filter(Boolean);
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
    job_families: job.job_family && job.job_family !== 'unknown' ? [job.job_family] : [],
    majors: job.majors || [],
    degree_min: job.degree_min,
    deadline: job.campaign?.deadline,
    status: job.status,
    apply_url: job.apply_url,
    source_url: job.source_url,
    source_domain: job.source_url ? new URL(job.source_url).hostname : '',
    source_level: job.source_level,
    quality_score: job.quality_score,
    risk_level: job.risk_level,
    tracker_status: null,
    is_favorite: false,
    tracker_note: '',
    next_action_at: null,
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
    state.clientMode = true;
    state.clientItems = items;
    state.total = items.length;
    state.page = 0;
    state.sortKey = 'match_score';
    state.sortDirection = 'desc';
    renderClientPage();
    $('resultSummary').textContent = `共 ${items.length} 个具体岗位，已按画像判断`;
    setSearchStatus(`画像匹配完成：${items.length} 个具体岗位`, 'success');
    switchView('opportunities', { load: false });
  } catch (error) {
    setSearchStatus(error.message, 'error');
  }
}

async function runResumeMatch() {
  const resumeText = $('resumeText').value.trim();
  if (resumeText.length < 20) {
    setSearchStatus('请先粘贴简历内容，或选择 TXT / Markdown 简历文件。', 'error');
    return;
  }
  setLoading(true);
  setSearchStatus('正在本机分析简历并匹配机会...');
  try {
    const filters = Object.fromEntries(searchParams({ all: true, trackedOnly: false }).entries());
    delete filters.offset;
    delete filters.limit;
    delete filters.tracked_only;
    const data = await fetchJson('/api/opportunities/match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resume_text: resumeText,
        target_cities: splitValues($('targetCities').value),
        preferred_job_families: splitValues($('targetJobFamilies').value),
        degree: $('degree').value,
        filters,
      }),
    });
    state.currentView = 'opportunities';
    state.clientMode = true;
    state.clientItems = data.items || [];
    state.total = state.clientItems.length;
    state.page = 0;
    state.sortKey = 'match_score';
    state.sortDirection = 'desc';
    renderClientPage();
    switchView('opportunities', { load: false });
    $('resultSummary').textContent = `共 ${state.total} 条机会，已按本地简历匹配度排序`;
    setSearchStatus(`简历匹配完成：${state.total} 条机会`, 'success');
  } catch (error) {
    setSearchStatus(error.message, 'error');
  } finally {
    setLoading(false);
  }
}

async function readResumeFile() {
  const file = $('resumeFile').files?.[0];
  if (!file) return;
  try {
    const text = await file.text();
    if (!text.trim()) throw new Error('文件中没有可读取的文本。');
    $('resumeText').value = text.slice(0, 100000);
    setSearchStatus(`已读取简历文件：${file.name}`, 'success');
  } catch (error) {
    setSearchStatus(`简历文件读取失败：${error.message}`, 'error');
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

function findOpportunity(id) {
  return state.clientItems.find((item) => item.id === id)
    || state.opportunities.find((item) => item.id === id);
}

function openTracker(id) {
  const item = findOpportunity(id);
  if (!item) return;
  state.currentTrackerItem = item;
  $('trackerDialogTitle').textContent = `${item.company_name} · ${item.title}`;
  $('trackerDialogStatus').value = item.tracker_status || 'saved';
  $('trackerFavorite').checked = Boolean(item.is_favorite || item.tracker_status === 'saved');
  $('trackerNextAction').value = formatDate(item.next_action_at, '');
  $('trackerNote').value = item.tracker_note || '';
  $('deleteTracker').hidden = !item.tracker_status && !item.is_favorite;
  $('trackerDialogStatusText').textContent = '';
  $('trackerDialog').showModal();
}

function applyTrackerResult(item, result) {
  item.tracker_status = result.status;
  item.is_favorite = Boolean(result.is_favorite);
  item.tracker_note = result.note || '';
  item.applied_at = result.applied_at || null;
  item.next_action_at = result.next_action_at || null;
  item.tracker_updated_at = result.updated_at || null;
}

async function saveTracking(event) {
  event.preventDefault();
  const item = state.currentTrackerItem;
  if (!item) return;
  $('trackerDialogStatusText').textContent = '正在保存...';
  const recordId = item.record_type === 'job' ? item.job_id : item.campaign_id;
  try {
    const result = await fetchJson(`/api/tracker/${encodeURIComponent(item.record_type)}/${Number(recordId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: $('trackerDialogStatus').value,
        is_favorite: $('trackerFavorite').checked,
        note: $('trackerNote').value,
        next_action_at: $('trackerNextAction').value || null,
      }),
    });
    applyTrackerResult(item, result);
    $('trackerDialog').close();
    if (state.clientMode) renderClientPage();
    else await loadOpportunities();
    setSearchStatus('投递进展已保存。', 'success');
  } catch (error) {
    $('trackerDialogStatusText').textContent = error.message;
  }
}

async function deleteTracking() {
  const item = state.currentTrackerItem;
  if (!item) return;
  const recordId = item.record_type === 'job' ? item.job_id : item.campaign_id;
  try {
    await fetchJson(`/api/tracker/${encodeURIComponent(item.record_type)}/${Number(recordId)}`, { method: 'DELETE' });
    item.tracker_status = null;
    item.is_favorite = false;
    item.tracker_note = '';
    item.applied_at = null;
    item.next_action_at = null;
    $('trackerDialog').close();
    if (state.clientMode) renderClientPage();
    else await loadOpportunities();
    setSearchStatus('投递记录已删除。', 'success');
  } catch (error) {
    $('trackerDialogStatusText').textContent = error.message;
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

function switchView(name, { load = true } = {}) {
  state.currentView = name;
  document.querySelectorAll('.view-tab').forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  const articlesActive = name === 'articles';
  $('opportunitiesView').classList.toggle('active', !articlesActive);
  $('opportunitiesView').hidden = articlesActive;
  $('articlesView').classList.toggle('active', articlesActive);
  $('articlesView').hidden = !articlesActive;
  if (articlesActive) {
    loadArticles();
  } else if (load) {
    state.clientMode = false;
    state.page = 0;
    loadOpportunities().catch((error) => setSearchStatus(error.message, 'error'));
  }
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
  $('jobFamily').value = '';
  $('major').value = '';
  $('sourceLevel').value = 'B';
  $('trackerStatus').value = '';
  $('includeExpired').checked = false;
  state.page = 0;
  state.clientMode = false;
  clearPresetState();
}

async function applyPreset(name, button) {
  resetFilters();
  state.currentView = 'opportunities';
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

function csvCell(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

async function exportCsv() {
  try {
    const items = state.clientMode
      ? state.clientItems
      : (await fetchJson(`/api/opportunities?${searchParams({ all: true }).toString()}`)).items || [];
    const headers = ['更新', '公司', '企业类型', '行业', '岗位/项目', '岗位方向', '专业', '批次', '届别', '地点', '截止', '来源等级', '投递状态', '投递时间', '下一步日期', '备注', '投递链接', '公告链接'];
    const rows = items.map((item) => [
      formatDate(item.updated_at, ''), item.company_name, item.company_type, item.industry,
      item.title, (item.job_families || []).join('、'), (item.majors || []).join('、'),
      item.recruitment_type, item.target_cohort, (item.cities || []).join('、'),
      item.deadline, item.source_level, TRACKER_LABELS[item.tracker_status] || '',
      formatDate(item.applied_at, ''), formatDate(item.next_action_at, ''), item.tracker_note,
      item.apply_url, item.source_url,
    ]);
    const csv = [headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\n');
    const blob = new Blob(['\ufeff', csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `job-radar-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    setSearchStatus(`已导出 ${items.length} 条记录。`, 'success');
  } catch (error) {
    setSearchStatus(`导出失败：${error.message}`, 'error');
  }
}

async function changePage(delta) {
  const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  const next = Math.max(0, Math.min(pages - 1, state.page + delta));
  if (next === state.page) return;
  state.page = next;
  if (state.clientMode) renderClientPage();
  else await loadOpportunities();
}

async function changePageSize() {
  state.pageSize = Number($('pageSize').value || 50);
  state.page = 0;
  if (state.clientMode) renderClientPage();
  else await loadOpportunities();
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

function initResponsiveFilters() {
  const details = $('advancedFilters');
  const mobile = window.matchMedia('(max-width: 720px)');
  const sync = (event) => {
    if (event.matches) details.removeAttribute('open');
    else details.setAttribute('open', '');
  };
  sync(mobile);
  mobile.addEventListener('change', sync);
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
    state.currentView = 'opportunities';
    state.clientMode = false;
    state.page = 0;
    await runSearch({ refresh: true });
  });
  $('resetFilters').addEventListener('click', async () => {
    resetFilters();
    state.currentView = 'opportunities';
    await runSearch({ refresh: false });
  });
  $('runResumeMatch').addEventListener('click', runResumeMatch);
  $('runMatch').addEventListener('click', runMatch);
  $('resumeFile').addEventListener('change', readResumeFile);
  $('importButton').addEventListener('click', importText);
  $('closeDialog').addEventListener('click', () => $('detailDialog').close());
  $('closeTrackerDialog').addEventListener('click', () => $('trackerDialog').close());
  $('trackerForm').addEventListener('submit', saveTracking);
  $('deleteTracker').addEventListener('click', deleteTracking);
  $('searchArticles').addEventListener('click', loadArticles);
  $('exportCsv').addEventListener('click', exportCsv);
  $('previousPage').addEventListener('click', () => changePage(-1));
  $('nextPage').addEventListener('click', () => changePage(1));
  $('pageSize').addEventListener('change', changePageSize);
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
    if (state.clientMode) renderClientPage();
    else renderOpportunities(state.opportunities);
  }));
}

async function init() {
  const campusYear = new Date().getMonth() + 1 >= 6 ? new Date().getFullYear() + 1 : new Date().getFullYear();
  $('autumnPreset').textContent = `${String(campusYear).slice(-2)}届热门秋招`;
  state.pageSize = Number($('pageSize').value || 50);
  initResponsiveFilters();
  initSplitter();
  bindEvents();
  loadStatus();
  loadArticles();
  const today = new Date().toISOString().slice(0, 10);
  const shouldRefresh = localStorage.getItem('jobRadarLastRefreshDate') !== today;
  await runSearch({ refresh: shouldRefresh });
}

init();
