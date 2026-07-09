const $ = (id) => document.getElementById(id);

function profile() {
  const cities = $('targetCities').value.split(',').map(s => s.trim()).filter(Boolean);
  const max = $('maxWrittenBurden').value;
  return {
    graduation_date: $('graduationDate').value || null,
    school_region: $('schoolRegion').value,
    degree: $('degree').value,
    target_cities: cities,
    max_written_test_burden: max === '' ? null : Number(max),
  };
}

function searchFilters() {
  const params = new URLSearchParams();
  const query = $('query').value.trim();
  const city = $('city').value.trim();
  const cohort = $('cohort').value.trim();
  const accepts = $('acceptsOverseas').value;
  if (query) params.set('query', query);
  if (city) params.set('city', city);
  if (cohort) params.set('cohort', cohort);
  if (accepts) params.set('accepts_overseas', accepts);
  return params;
}

async function loadSignals() {
  const res = await fetch('/api/signals');
  const data = await res.json();
  $('signals').innerHTML = data.items.map(signalCard).join('') || '<p class="subtle">暂无信号</p>';
}

function signalCard(s) {
  const sourceLink = s.source_url ? `<p class="subtle">${escapeHtml(s.source_url)}</p>` : '';
  return `<article class="card">
    <h3>${escapeHtml(s.title)}</h3>
    <div class="meta">
      <span class="tag">${escapeHtml(s.company_name || '未知公司')}</span>
      <span class="tag">${escapeHtml(s.signal_type)}</span>
      <span class="tag good">来源 ${escapeHtml(s.source_level)}</span>
      <span class="tag warn">${escapeHtml(s.status)}</span>
    </div>
    <p>${escapeHtml(s.description || '')}</p>
    <p class="subtle">${escapeHtml(s.evidence_text || '')}</p>
    ${sourceLink}
  </article>`;
}

async function loadJobs() {
  const params = searchFilters();
  const res = await fetch('/api/jobs?' + params.toString());
  const data = await res.json();
  $('count').textContent = `${data.count} 条`;
  $('jobs').innerHTML = data.items.map(job => jobCard(job)).join('') || '<p class="subtle">没有匹配岗位</p>';
}

async function runMatch() {
  const filters = Object.fromEntries(searchFilters().entries());
  if (filters.max_written_test_burden) filters.max_written_test_burden = Number(filters.max_written_test_burden);
  const res = await fetch('/api/match', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile: profile(), filters }),
  });
  const data = await res.json();
  $('count').textContent = `${data.count} 条，已按画像判断`;
  $('jobs').innerHTML = data.items.map(item => jobCard(item.job, item.match)).join('') || '<p class="subtle">没有匹配岗位</p>';
}

function jobCard(job, match) {
  const statusClass = match ? matchClass(match.status) : '';
  const matchTag = match ? `<span class="tag ${statusClass}">${matchLabel(match.status)} ${Math.round(match.score * 100)}%</span>` : '<span class="tag">未匹配</span>';
  const process = job.process_rule || {};
  const campaign = job.campaign || {};
  const company = job.company || {};
  const companyName = company.name || '未知公司';
  const cityText = (job.cities || []).join(' / ') || '城市未知';
  const deadline = campaign.deadline || '未知';
  const degree = degreeLabel(job.degree_min || campaign.degree_min || '');
  const burden = Number(process.written_test_burden ?? 5);
  const burdenClass = burden <= 1 ? 'good' : burden >= 4 ? 'bad' : 'warn';
  const applyUrl = job.apply_url || job.source_url || campaign.apply_url || campaign.source_url || '';
  const sourceUrl = job.source_url || campaign.source_url || '';
  const sourceAction = sourceUrl && sourceUrl !== applyUrl ? `<a class="button ghost" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">原文</a>` : '';
  return `<article class="card job-card">
    <div class="job-main">
      <div class="job-topline">
        <div class="job-title-block">
          <div class="job-title-row">
            <h3 class="job-title">${escapeHtml(job.title || '待命名岗位')}</h3>
            ${matchTag}
          </div>
          <p class="job-company">${escapeHtml(companyName)}<span>${escapeHtml(campaign.name || '未知招聘项目')}</span></p>
        </div>
        <div class="job-deadline">
          <span>截止</span>
          <strong>${escapeHtml(deadline)}</strong>
        </div>
      </div>
      <div class="job-facts">
        <span>${escapeHtml(cityText)}</span>
        <span>${escapeHtml(campaign.target_cohort || '未知届别')}</span>
        <span>${escapeHtml(campaign.recruitment_type || '未知类型')}</span>
        <span>${escapeHtml(degree)}</span>
        <span class="${burdenClass}">笔试负担 ${escapeHtml(burden)}</span>
        <span>来源 ${escapeHtml(job.source_level || 'C')}</span>
      </div>
      <p class="job-description">${escapeHtml(job.description || '暂无岗位说明，建议打开原文复核。')}</p>
      <p class="subtle">海外：${campaign.accepts_overseas === true ? '接受' : campaign.accepts_overseas === false ? '未显示接受' : '未知'}</p>
      ${match ? renderMatch(match) : ''}
    </div>
    <div class="job-actions">
      ${applyUrl ? `<a class="button primary" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener">去申请</a>` : ''}
      ${sourceAction}
      <button class="ghost" onclick="showDetail(${job.id})">证据</button>
    </div>
  </article>`;
}

function renderMatch(match) {
  const reasons = (match.reasons || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
  const risks = (match.risks || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
  const blockers = (match.blockers || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
  return `<div>
    ${reasons ? `<p><b>匹配原因</b></p><ul class="reason-list">${reasons}</ul>` : ''}
    ${risks ? `<p><b>风险或未知</b></p><ul class="reason-list">${risks}</ul>` : ''}
    ${blockers ? `<p><b>不匹配原因</b></p><ul class="reason-list">${blockers}</ul>` : ''}
  </div>`;
}

async function showDetail(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`);
  const job = await res.json();
  const evidence = (job.evidence || []).map(e => `<li><b>${escapeHtml(e.field_name)}</b>：${escapeHtml(e.value_text || '')}<br><span class="subtle">${escapeHtml(e.evidence_text || '')}</span></li>`).join('');
  const changes = (job.changes || []).map(c => `<li>${escapeHtml(c.detected_at)}：${escapeHtml(c.field_name)} 从 ${escapeHtml(c.old_value || '空')} 改为 ${escapeHtml(c.new_value || '空')}</li>`).join('');
  $('detailContent').innerHTML = `<h2>${escapeHtml(job.title)}</h2>
    <p>${escapeHtml(job.company.name)} ｜ ${escapeHtml(job.campaign.name)}</p>
    <h3>流程说明</h3><p>${escapeHtml(job.process_rule.process_text || '暂无')}</p>
    <h3>证据</h3><ul>${evidence || '<li>暂无证据，需人工复核。</li>'}</ul>
    <h3>变化记录</h3><ul>${changes || '<li>暂无变化记录。</li>'}</ul>`;
  $('detailDialog').showModal();
}

async function importText() {
  const body = {
    company_name: $('importCompany').value,
    job_title: $('importTitle').value,
    source_url: $('importUrl').value,
    source_level: $('importSourceLevel').value,
    text: $('importText').value,
  };
  const res = await fetch('/api/admin/import-text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  $('importResult').textContent = JSON.stringify(data, null, 2);
  await Promise.all([loadSignals(), loadJobs()]);
}

function matchClass(status) {
  if (status === 'eligible') return 'good';
  if (status === 'not_eligible') return 'bad';
  return 'warn';
}
function matchLabel(status) {
  return { eligible: '可投', maybe: '可能可投', not_eligible: '不适合', unknown: '未知' }[status] || status;
}
function degreeLabel(value) {
  return {
    associate: '专科',
    bachelor: '本科',
    master: '硕士',
    phd: '博士',
  }[value] || value || '学历未知';
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[ch]));
}
async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || `请求失败：${res.status}`);
  }
  return data;
}
function showResult(id, value) {
  const el = $(id);
  if (!el) return;
  el.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
function formatAutoImportResult(data) {
  const jobMap = new Map((data.jobs || []).map(job => [String(job.id), job]));
  const lines = [
    `搜索词：${data.keyword || ''}`,
    `信息源：${sourceScopeLabel(data.source_scope || 'all')}`,
    `总计：找到 ${data.count || 0} 条，成功导入 ${data.imported || 0} 条，生成岗位 ${data.jobs_imported || 0} 个`,
  ];
  for (const provider of data.providers || []) {
    const label = {
      google: 'Google',
      bing: 'Bing',
      sogou: '搜狗微信',
      official_catalog: '官方目录',
    }[provider.provider] || provider.provider;
    lines.push(`${label}：找到 ${provider.count || 0} 条，导入 ${provider.imported || 0} 条，生成岗位 ${provider.jobs_imported || 0} 个${provider.error ? `，失败：${provider.error}` : ''}`);
    for (const item of provider.items || []) {
      if (item.imported) {
        const type = item.candidate_type === 'wechat_article' ? '公众号文章' : '招聘信号';
        lines.push(`  已导入${type}：${item.canonical_url}`);
        const summaries = (item.job_ids || []).map(id => jobMap.get(String(id))).filter(Boolean);
        if (summaries.length) {
          lines.push('    已生成岗位：');
          for (const job of summaries) lines.push(`      ${formatImportedJob(job)}`);
        } else if ((item.job_ids || []).length) {
          lines.push(`    已生成岗位 ID：${item.job_ids.join(', ')}`);
        }
      } else if (item.error) {
        lines.push(`  未导入：${item.canonical_url || item.url} ｜ ${item.error}`);
      }
    }
  }
  return lines.join('\n');
}
function formatImportedJob(job) {
  const city = (job.cities || []).join(' / ') || '城市未知';
  const deadline = job.deadline || '截止未知';
  return `${job.title || '待命名岗位'} ｜ ${job.company_name || '未知公司'} ｜ ${city} ｜ ${deadline}`;
}
function sourceScopeLabel(value) {
  return {
    all: '综合',
    official: '企业官网',
    job_boards: '招聘平台',
    open_web: '开源/社区',
    university: '高校就业网',
    wechat: '公众号',
  }[value] || value;
}

$('searchBtn').addEventListener('click', async () => {
  await loadJobs();
  switchTab('jobs');
});
$('runMatch').addEventListener('click', async () => {
  await runMatch();
  switchTab('jobs');
});
$('refreshSignals').addEventListener('click', loadSignals);
$('importBtn').addEventListener('click', importText);
$('closeDialog').addEventListener('click', () => $('detailDialog').close());

loadSignals();
loadJobs();

function wechatParams() {
  const params = new URLSearchParams();
  const q = $('wechatQuery')?.value?.trim() || '';
  const freshness = $('wechatFreshnessDays')?.value || '45';
  const minSource = $('wechatMinSourceLevel')?.value || '';
  const trusted = $('wechatTrustedOnly')?.value || 'false';
  if (q) params.set('q', q);
  params.set('freshness_days', freshness);
  if (minSource) params.set('min_source_level', minSource);
  params.set('trusted_only', trusted);
  return params;
}

async function loadWechatArticles() {
  if (!$('wechatResults')) return;
  const res = await fetch('/api/wechat/articles?' + wechatParams().toString());
  const data = await res.json();
  $('wechatResults').innerHTML = data.items.map(wechatArticleCard).join('') || '<p class="subtle">暂无匹配公众号文章。可以先导入 HTML，或由后台发现任务补充。</p>';
}

function wechatArticleCard(article) {
  const stale = article.is_stale ? '<span class="tag warn">可能过期</span>' : '<span class="tag good">新鲜</span>';
  const blocked = article.is_blocked_source ? '<span class="tag bad">低质来源</span>' : '';
  return `<article class="card">
    <h3>${escapeHtml(article.title)}</h3>
    <div class="meta">
      ${stale}
      ${blocked}
      <span class="tag">${escapeHtml(article.account_name || '未知公众号')}</span>
      <span class="tag">来源 ${escapeHtml(article.source_level || 'C')}</span>
      <span class="tag">质量 ${Math.round((article.quality_score || 0) * 100)}%</span>
      <span class="tag">新鲜度 ${Math.round((article.freshness_score || 0) * 100)}%</span>
    </div>
    <p>${escapeHtml(article.digest || (article.content_text || '').slice(0, 180))}</p>
    <p class="subtle">发布时间：${escapeHtml(article.publish_at || '未知')} ｜ 首次发现：${escapeHtml(article.first_seen_at || '')}</p>
    <p class="subtle">${escapeHtml(article.canonical_url)}</p>
  </article>`;
}

async function loadWechatSources() {
  if (!$('wechatSources')) return;
  const res = await fetch('/api/wechat/sources');
  const data = await res.json();
  $('wechatSources').innerHTML = data.items.map(s => `<span class="tag ${s.trust_level === 'S' || s.trust_level === 'A' ? 'good' : ''}">${escapeHtml(s.name)} · ${escapeHtml(s.trust_level)} · ${s.enabled ? '启用' : '关闭'}</span>`).join('');
}

async function loadWechatConfig() {
  if (!$('wechatConfigStatus')) return;
  try {
    const data = await fetchJson('/api/wechat/config');
    const parts = [
      data.personal_mode ? '<span class="tag good">个人本地模式</span>' : '<span class="tag warn">普通模式</span>',
      data.public_fetch_enabled ? '<span class="tag good">文章抓取已开启</span>' : '<span class="tag warn">文章抓取未开启</span>',
      data.web_search_import_enabled ? '<span class="tag good">网页搜索导入已开启</span>' : '<span class="tag warn">网页搜索导入未开启</span>',
      data.sogou_discovery_enabled ? '<span class="tag good">搜狗联网已开启</span>' : '<span class="tag">搜狗联网未开启</span>',
    ];
    $('wechatConfigStatus').innerHTML = parts.join('');
  } catch (err) {
    $('wechatConfigStatus').innerHTML = `<span class="tag bad">${escapeHtml(err.message)}</span>`;
  }
}

async function autoSearchImportWechat() {
  const button = $('wechatAutoImportBtn');
  const body = {
    keyword: $('wechatDiscoverKeyword').value.trim(),
    provider: $('wechatSearchProvider').value,
    source_scope: $('sourceScope').value,
    freshness_days: Number($('wechatDiscoverFreshness').value || 45),
    max_results: Number($('wechatAutoImportLimit').value || 10),
  };
  if (!body.keyword) {
    showResult('wechatQuickResult', '请先输入搜索词。');
    return;
  }
  showResult('wechatQuickResult', '正在用普通网页搜索查找招聘线索，并自动导入...');
  if (button) button.disabled = true;
  try {
    const data = await fetchJson('/api/jobs/auto-search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    showResult('wechatQuickResult', formatAutoImportResult(data));
    await Promise.all([loadSignals(), loadWechatArticles(), loadWechatConfig()]);
    if ((data.jobs_imported || 0) > 0) {
      await runMatch();
      switchTab('jobs');
    } else {
      await loadJobs();
      switchTab('signals');
    }
  } catch (err) {
    showResult('wechatQuickResult', err.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function openWechatSearch(provider) {
  const keyword = $('wechatDiscoverKeyword').value.trim() || $('wechatQuery').value.trim() || '秋招';
  const freshness = $('wechatDiscoverFreshness').value || '45';
  const sourceScope = $('sourceScope')?.value || 'all';
  const tab = window.open('about:blank', '_blank');
  if (tab) tab.opener = null;
  try {
    const data = await fetchJson(`/api/wechat/search-links?keyword=${encodeURIComponent(keyword)}&freshness_days=${encodeURIComponent(freshness)}&source_scope=${encodeURIComponent(sourceScope)}`);
    const url = data.urls?.[provider];
    if (!url) throw new Error('没有生成搜索链接');
    if (tab) {
      tab.location.href = url;
    } else {
      window.location.href = url;
    }
    const label = provider === 'google' ? 'Google' : provider === 'bing' ? 'Bing' : '搜狗微信';
    showResult('wechatQuickResult', `已打开 ${label} 搜索页。`);
  } catch (err) {
    if (tab) tab.close();
    showResult('wechatQuickResult', err.message);
  }
}

$('wechatSearchBtn')?.addEventListener('click', async () => {
  await loadWechatArticles();
  switchTab('articles');
});
$('wechatSourcesBtn')?.addEventListener('click', loadWechatSources);
$('wechatAutoImportBtn')?.addEventListener('click', autoSearchImportWechat);
$('openGoogleBtn')?.addEventListener('click', () => openWechatSearch('google'));
$('openBingBtn')?.addEventListener('click', () => openWechatSearch('bing'));
$('openSogouBtn')?.addEventListener('click', () => openWechatSearch('sogou'));
document.querySelectorAll('.tab').forEach(button => {
  button.addEventListener('click', () => switchTab(button.dataset.tab));
});
initSplitter();
loadWechatConfig();
loadWechatSources();
loadWechatArticles();

function switchTab(name) {
  const tabName = name || 'signals';
  document.querySelectorAll('.tab').forEach(button => {
    button.classList.toggle('active', button.dataset.tab === tabName);
  });
  const panels = {
    signals: $('signalsPanel'),
    jobs: $('jobsPanel'),
    articles: $('articlesPanel'),
  };
  Object.entries(panels).forEach(([key, panel]) => {
    panel?.classList.toggle('active', key === tabName);
  });
}

function initSplitter() {
  const workspace = $('workspace');
  const splitter = $('splitter');
  if (!workspace || !splitter) return;
  const saved = localStorage.getItem('jobRadarLeftWidth');
  if (saved) workspace.style.setProperty('--left-width', saved);
  let dragging = false;
  splitter.addEventListener('pointerdown', (event) => {
    dragging = true;
    splitter.setPointerCapture(event.pointerId);
    document.body.classList.add('is-resizing');
  });
  splitter.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const rect = workspace.getBoundingClientRect();
    const width = Math.min(Math.max(event.clientX - rect.left, 300), Math.min(640, rect.width - 420));
    const value = `${Math.round(width)}px`;
    workspace.style.setProperty('--left-width', value);
    localStorage.setItem('jobRadarLeftWidth', value);
  });
  function stopDrag(event) {
    if (!dragging) return;
    dragging = false;
    try { splitter.releasePointerCapture(event.pointerId); } catch (_) {}
    document.body.classList.remove('is-resizing');
  }
  splitter.addEventListener('pointerup', stopDrag);
  splitter.addEventListener('pointercancel', stopDrag);
}
