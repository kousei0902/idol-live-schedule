(() => {
  'use strict';

  const STORAGE_KEY = 'oshisuke_lives_v1';
  const GROUP_COLOR_KEY = 'oshisuke_group_colors_v1';
  const FAVORITE_GROUPS_KEY = 'oshisuke_favorite_groups_v1';
  const FAVORITES_FILTER = '__favorites__';
  const COLOR_PALETTE = ['#ff5fa2', '#7c6cf0', '#2fb380', '#e8a53d', '#3ab0d8', '#e0507a', '#8c6cf0', '#4fb0a5'];
  const DOW = ['日', '月', '火', '水', '木', '金', '土'];
  const EVENTS_JSON_URL = 'https://raw.githubusercontent.com/kousei0902/idol-live-schedule/main/events.json';
  const PREFECTURES = [
    '北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
    '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
    '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県',
    '岐阜県', '静岡県', '愛知県', '三重県',
    '滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県',
    '鳥取県', '島根県', '岡山県', '広島県', '山口県',
    '徳島県', '香川県', '愛媛県', '高知県',
    '福岡県', '佐賀県', '長崎県', '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県',
  ];

  const $ = (sel) => document.querySelector(sel);

  const els = {
    list: $('#list'),
    emptyState: $('#emptyState'),
    nextLiveCard: $('#nextLiveCard'),
    nextLiveDays: $('#nextLiveDays'),
    nextLiveDetail: $('#nextLiveDetail'),
    tabs: $('#statusTabs'),
    filterbar: $('#filterbar'),
    searchToggleBtn: $('#searchToggleBtn'),
    searchInput: $('#searchInput'),
    groupChips: $('#groupChips'),
    addBtn: $('#addBtn'),
    modalOverlay: $('#modalOverlay'),
    modalTitle: $('#modalTitle'),
    closeModalBtn: $('#closeModalBtn'),
    form: $('#liveForm'),
    fId: $('#liveId'),
    fGroup: $('#fGroup'),
    fTitle: $('#fTitle'),
    fDate: $('#fDate'),
    fTime: $('#fTime'),
    fVenue: $('#fVenue'),
    fStatus: $('#fStatus'),
    fMemo: $('#fMemo'),
    groupList: $('#groupList'),
    deleteBtn: $('#deleteBtn'),
    discoverToggleBtn: $('#discoverToggleBtn'),
    discoverOverlay: $('#discoverOverlay'),
    closeDiscoverBtn: $('#closeDiscoverBtn'),
    discoverSearchInput: $('#discoverSearchInput'),
    discoverDateInput: $('#discoverDateInput'),
    discoverDateClearBtn: $('#discoverDateClearBtn'),
    discoverPrefSelect: $('#discoverPrefSelect'),
    discoverMeta: $('#discoverMeta'),
    discoverList: $('#discoverList'),
    discoverFavToggleBtn: $('#discoverFavToggleBtn'),
    discoverFavChips: $('#discoverFavChips'),
  };

  let state = {
    lives: loadLives(),
    activeTab: 'upcoming',
    activeGroup: null,
    query: '',
    favoriteGroups: loadFavoriteGroups(),
  };

  let discoverState = {
    events: null,   // null = not loaded yet
    error: null,
    loading: false,
  };

  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function pad(n) { return String(n).padStart(2, '0'); }

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  function seedData() {
    const t = new Date();
    const offset = (days) => {
      const d = new Date(t);
      d.setDate(d.getDate() + days);
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    };
    return [
      {
        id: uid(), group: 'サンプル☆スターズ', title: '夏の単独公演 2026',
        date: offset(5), time: '18:00', venue: 'Zepp DiverCity',
        status: 'go', memo: 'チケット: アリーナ整理番号120番台'
      },
      {
        id: uid(), group: 'サンプル☆スターズ', title: '定期公演 vol.12',
        date: offset(19), time: '19:00', venue: '渋谷公会堂',
        status: 'interested', memo: ''
      },
      {
        id: uid(), group: 'ネオンドール', title: '対バンライブ「STARLIGHT」',
        date: offset(33), time: '17:30', venue: '大阪城ホール',
        status: 'undecided', memo: '遠征になるので要検討'
      },
      {
        id: uid(), group: 'ネオンドール', title: '春ツアー ファイナル',
        date: offset(-10), time: '18:30', venue: '幕張メッセ',
        status: 'go', memo: '楽しかった!'
      },
    ];
  }

  function loadLives() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
      const seeded = seedData();
      localStorage.setItem(STORAGE_KEY, JSON.stringify(seeded));
      return seeded;
    } catch (e) {
      return [];
    }
  }

  function saveLives() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.lives));
  }

  function loadFavoriteGroups() {
    try {
      const raw = JSON.parse(localStorage.getItem(FAVORITE_GROUPS_KEY));
      return Array.isArray(raw) ? raw : [];
    } catch (e) { return []; }
  }
  function saveFavoriteGroups() {
    localStorage.setItem(FAVORITE_GROUPS_KEY, JSON.stringify(state.favoriteGroups));
  }
  function isFavoriteGroup(name) {
    return state.favoriteGroups.includes(name);
  }
  function toggleFavoriteGroup(name) {
    name = (name || '').trim();
    if (!name) return;
    const idx = state.favoriteGroups.indexOf(name);
    if (idx >= 0) state.favoriteGroups.splice(idx, 1);
    else state.favoriteGroups.push(name);
    saveFavoriteGroups();
  }

  function loadGroupColors() {
    try {
      return JSON.parse(localStorage.getItem(GROUP_COLOR_KEY)) || {};
    } catch (e) { return {}; }
  }
  function saveGroupColors(map) {
    localStorage.setItem(GROUP_COLOR_KEY, JSON.stringify(map));
  }
  function colorForGroup(group) {
    const map = loadGroupColors();
    if (map[group]) return map[group];
    const used = Object.values(map);
    const next = COLOR_PALETTE.find((c) => !used.includes(c)) ||
      COLOR_PALETTE[Object.keys(map).length % COLOR_PALETTE.length];
    map[group] = next;
    saveGroupColors(map);
    return next;
  }

  function allGroups() {
    return [...new Set(state.lives.map((l) => l.group))].sort();
  }

  function formatDateLabel(dateStr) {
    const [y, m, d] = dateStr.split('-').map(Number);
    const dow = DOW[new Date(y, m - 1, d).getDay()];
    return { m, d, dow };
  }

  function monthLabel(dateStr) {
    const [y, m] = dateStr.split('-').map(Number);
    return `${y}年${m}月`;
  }

  function computeStatusBucket(live) {
    if (live.date < todayStr()) return live.status === 'go' ? 'attended' : 'done';
    return live.status; // go | interested | undecided
  }

  function statusLabel(bucket) {
    return { go: '参戦する', interested: '気になる', undecided: '未定', done: '終了', attended: '参戦済み' }[bucket] || bucket;
  }

  function renderGroupChips() {
    const groups = allGroups();
    els.groupChips.innerHTML = '';
    const allChip = document.createElement('button');
    allChip.className = 'chip' + (state.activeGroup === null ? ' active' : '');
    allChip.textContent = 'すべて';
    allChip.onclick = () => { state.activeGroup = null; render(); };
    els.groupChips.appendChild(allChip);

    if (state.favoriteGroups.length) {
      const favChip = document.createElement('button');
      favChip.className = 'chip chip-favorite' + (state.activeGroup === FAVORITES_FILTER ? ' active' : '');
      favChip.textContent = '★ お気に入り';
      favChip.onclick = () => {
        state.activeGroup = state.activeGroup === FAVORITES_FILTER ? null : FAVORITES_FILTER;
        render();
      };
      els.groupChips.appendChild(favChip);
    }

    groups.forEach((g) => {
      const chip = document.createElement('button');
      chip.className = 'chip chip-group' + (state.activeGroup === g ? ' active' : '');

      const star = document.createElement('span');
      star.className = 'chip-star' + (isFavoriteGroup(g) ? ' is-favorite' : '');
      star.textContent = isFavoriteGroup(g) ? '★' : '☆';
      star.setAttribute('role', 'button');
      star.setAttribute('aria-label', 'お気に入り切替');
      star.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleFavoriteGroup(g);
        render();
      });
      chip.appendChild(star);
      chip.appendChild(document.createTextNode(g));
      chip.addEventListener('click', () => {
        state.activeGroup = state.activeGroup === g ? null : g;
        render();
      });
      els.groupChips.appendChild(chip);
    });
  }

  function updateGroupDatalist() {
    els.groupList.innerHTML = allGroups().map((g) => `<option value="${escapeHtml(g)}">`).join('');
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function filteredLives() {
    const q = state.query.trim().toLowerCase();
    const isAttendedTab = state.activeTab === 'attended';
    const result = state.lives.filter((l) => {
      const bucket = computeStatusBucket(l);
      if (state.activeTab === 'upcoming' && (bucket === 'done' || bucket === 'attended')) return false;
      if (state.activeTab !== 'all' && state.activeTab !== 'upcoming' && bucket !== state.activeTab) return false;
      if (state.activeGroup === FAVORITES_FILTER) {
        if (!isFavoriteGroup(l.group)) return false;
      } else if (state.activeGroup && l.group !== state.activeGroup) return false;
      if (q) {
        const hay = `${l.group} ${l.title} ${l.venue}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    // History reads newest-first; every other tab reads soonest-first.
    result.sort((a, b) => isAttendedTab
      ? (b.date.localeCompare(a.date) || (b.time || '').localeCompare(a.time || ''))
      : (a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || '')));
    return result;
  }

  function renderNextLive() {
    const upcoming = state.lives
      .filter((l) => l.date >= todayStr() && l.status !== 'undecided')
      .sort((a, b) => a.date.localeCompare(b.date))[0]
      || state.lives.filter((l) => l.date >= todayStr()).sort((a, b) => a.date.localeCompare(b.date))[0];

    if (!upcoming) {
      els.nextLiveCard.hidden = true;
      return;
    }
    els.nextLiveCard.hidden = false;
    const today = new Date(todayStr());
    const target = new Date(upcoming.date);
    const diffDays = Math.round((target - today) / 86400000);
    els.nextLiveDays.textContent = diffDays <= 0 ? '本日' : diffDays;
    if (diffDays <= 0) els.nextLiveDays.nextElementSibling.style.display = 'none';
    else els.nextLiveDays.nextElementSibling.style.display = '';

    els.nextLiveDetail.innerHTML =
      `<strong>${escapeHtml(upcoming.group)}</strong> ${escapeHtml(upcoming.title || '')}<br>` +
      `${upcoming.date}${upcoming.time ? ' ' + upcoming.time : ''}${upcoming.venue ? ' ／ ' + escapeHtml(upcoming.venue) : ''}`;
  }

  function renderList() {
    const lives = filteredLives();
    els.list.innerHTML = '';
    els.emptyState.hidden = lives.length !== 0;

    let lastMonth = null;
    lives.forEach((live) => {
      const mLabel = monthLabel(live.date);
      if (mLabel !== lastMonth) {
        const h = document.createElement('div');
        h.className = 'month-header';
        h.textContent = mLabel;
        els.list.appendChild(h);
        lastMonth = mLabel;
      }
      els.list.appendChild(renderCard(live));
    });
  }

  function renderCard(live) {
    const { m, d, dow } = formatDateLabel(live.date);
    const bucket = computeStatusBucket(live);
    const isToday = live.date === todayStr();

    const card = document.createElement('div');
    card.className = 'card' + (isToday ? ' is-today' : '');
    card.innerHTML = `
      <div class="card-date">
        <div class="dow">${dow}</div>
        <div class="day">${d}</div>
      </div>
      <div class="card-body">
        <div class="card-top">
          <span class="group-dot" style="background:${colorForGroup(live.group)}"></span>
          <span class="group-name">${escapeHtml(live.group)}</span>
        </div>
        <div class="card-title">${escapeHtml(live.title || '(タイトル未設定)')}</div>
        <div class="card-meta">
          ${live.time ? `<span>${live.time}〜</span>` : ''}
          ${live.venue ? `<span>${escapeHtml(live.venue)}</span>` : ''}
        </div>
        <span class="status-badge status-${bucket}">${statusLabel(bucket)}</span>
      </div>
    `;
    card.addEventListener('click', () => openModal(live));
    return card;
  }

  function render() {
    renderGroupChips();
    updateGroupDatalist();
    renderNextLive();
    renderList();
  }

  // Tabs
  els.tabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    els.tabs.querySelectorAll('.tab').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.activeTab = btn.dataset.status;
    renderList();
  });

  // Search toggle
  els.searchToggleBtn.addEventListener('click', () => {
    els.filterbar.hidden = !els.filterbar.hidden;
    if (!els.filterbar.hidden) els.searchInput.focus();
  });
  els.searchInput.addEventListener('input', (e) => {
    state.query = e.target.value;
    renderList();
  });

  // Modal
  function openModal(live) {
    els.form.reset();
    if (live) {
      els.modalTitle.textContent = 'ライブを編集';
      els.fId.value = live.id;
      els.fGroup.value = live.group;
      els.fTitle.value = live.title || '';
      els.fDate.value = live.date;
      els.fTime.value = live.time || '';
      els.fVenue.value = live.venue || '';
      els.fStatus.value = live.status;
      els.fMemo.value = live.memo || '';
      els.deleteBtn.hidden = false;
    } else {
      els.modalTitle.textContent = 'ライブを追加';
      els.fId.value = '';
      els.fDate.value = todayStr();
      els.fStatus.value = 'interested';
      els.deleteBtn.hidden = true;
    }
    updateGroupDatalist();
    els.modalOverlay.hidden = false;
  }

  function closeModal() {
    els.modalOverlay.hidden = true;
  }

  els.addBtn.addEventListener('click', () => openModal(null));
  els.closeModalBtn.addEventListener('click', closeModal);
  els.modalOverlay.addEventListener('click', (e) => {
    if (e.target === els.modalOverlay) closeModal();
  });

  els.form.addEventListener('submit', (e) => {
    e.preventDefault();
    const id = els.fId.value || uid();
    const live = {
      id,
      group: els.fGroup.value.trim(),
      title: els.fTitle.value.trim(),
      date: els.fDate.value,
      time: els.fTime.value,
      venue: els.fVenue.value.trim(),
      status: els.fStatus.value,
      memo: els.fMemo.value.trim(),
    };
    if (!live.group || !live.date) return;

    const idx = state.lives.findIndex((l) => l.id === id);
    if (idx >= 0) state.lives[idx] = live;
    else state.lives.push(live);

    saveLives();
    closeModal();
    render();
  });

  els.deleteBtn.addEventListener('click', () => {
    const id = els.fId.value;
    if (!id) return;
    if (!confirm('このライブ予定を削除しますか?')) return;
    state.lives = state.lives.filter((l) => l.id !== id);
    saveLives();
    closeModal();
    render();
  });

  // ---- Discover (search collected event data) ----

  async function loadDiscoveredEvents() {
    if (discoverState.events || discoverState.loading) return;
    discoverState.loading = true;
    discoverState.error = null;
    renderDiscoverList();
    try {
      const res = await fetch(EVENTS_JSON_URL, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = await res.json();
      const events = Object.entries(raw).map(([url, ev]) => ({ url, ...ev }));
      events.sort((a, b) => {
        if (!a.date && !b.date) return 0;
        if (!a.date) return 1;
        if (!b.date) return -1;
        return a.date.localeCompare(b.date);
      });
      discoverState.events = events;
    } catch (err) {
      discoverState.error = err;
    } finally {
      discoverState.loading = false;
      renderDiscoverList();
    }
  }

  function filteredDiscoverEvents() {
    if (!discoverState.events) return [];
    const q = els.discoverSearchInput.value.trim().toLowerCase();
    const dateFilter = els.discoverDateInput.value;
    const prefFilter = els.discoverPrefSelect.value;
    return discoverState.events.filter((ev) => {
      if (dateFilter && ev.date !== dateFilter) return false;
      if (prefFilter && ev.prefecture !== prefFilter) return false;
      if (!q) return true;
      const hay = `${ev.group || ''} ${ev.title || ''} ${ev.venue || ''}`.toLowerCase();
      return hay.includes(q);
    });
  }

  function updateDiscoverFavToggle() {
    const q = els.discoverSearchInput.value.trim();
    const active = !!q && isFavoriteGroup(q);
    els.discoverFavToggleBtn.textContent = active ? '★' : '☆';
    els.discoverFavToggleBtn.classList.toggle('is-favorite', active);
    els.discoverFavToggleBtn.disabled = !q;
  }

  function renderDiscoverFavChips() {
    els.discoverFavChips.innerHTML = '';
    state.favoriteGroups.forEach((name) => {
      const chip = document.createElement('span');
      chip.className = 'discover-fav-chip';

      const label = document.createElement('button');
      label.type = 'button';
      label.className = 'discover-fav-chip-label';
      label.textContent = name;
      label.addEventListener('click', () => {
        els.discoverSearchInput.value = name;
        updateDiscoverFavToggle();
        renderDiscoverList();
      });

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'discover-fav-chip-remove';
      remove.setAttribute('aria-label', `${name}をお気に入りから削除`);
      remove.textContent = '×';
      remove.addEventListener('click', () => {
        toggleFavoriteGroup(name);
        renderDiscoverFavChips();
        updateDiscoverFavToggle();
      });

      chip.appendChild(label);
      chip.appendChild(remove);
      els.discoverFavChips.appendChild(chip);
    });
  }

  function sourceLabel(ev) {
    // Show the actual ticket-selling site the link goes to, not the
    // watchlist entry that found it (liveidol.blog is an aggregator -
    // its entries' urls point at tiget/ticketdive/etc., which is the
    // more useful thing to show here).
    try {
      return new URL(ev.url).hostname.replace(/^www\./, '');
    } catch (err) {
      return ev.source || '';
    }
  }

  function renderDiscoverList() {
    els.discoverList.innerHTML = '';

    if (discoverState.loading) {
      els.discoverMeta.textContent = '読み込み中...';
      return;
    }
    if (discoverState.error) {
      els.discoverMeta.textContent = '取得に失敗しました。通信環境を確認してもう一度開いてみてください。';
      return;
    }
    if (!discoverState.events) return;

    const results = filteredDiscoverEvents();
    els.discoverMeta.textContent = `${discoverState.events.length}件中 ${results.length}件`;

    results.slice(0, 200).forEach((ev) => {
      const item = document.createElement('div');
      item.className = 'discover-item';
      item.innerHTML = `
        <div class="discover-item-main">
          <span class="discover-source">${escapeHtml(sourceLabel(ev))}</span>
          <div class="discover-group">${escapeHtml(ev.group || ev.title || '(不明)')}</div>
          <div class="discover-title">${escapeHtml(ev.title || '')}</div>
          <div class="discover-sub">${escapeHtml(ev.date || '日付不明')} ／ ${escapeHtml(ev.venue || '会場不明')}</div>
        </div>
        <div class="discover-actions">
          <button type="button" class="discover-add-btn">追加</button>
          <a class="discover-link" href="${escapeHtml(ev.url)}" target="_blank" rel="noopener">元ページ</a>
        </div>
      `;
      item.querySelector('.discover-add-btn').addEventListener('click', () => {
        openModal(null);
        els.fGroup.value = ev.group || ev.title || '';
        els.fTitle.value = ev.title || '';
        if (ev.date) els.fDate.value = ev.date;
        els.fVenue.value = ev.venue || '';
        els.fMemo.value = ev.url || '';
      });
      els.discoverList.appendChild(item);
    });
  }

  function openDiscover() {
    els.discoverOverlay.hidden = false;
    els.discoverSearchInput.focus();
    renderDiscoverFavChips();
    updateDiscoverFavToggle();
    loadDiscoveredEvents();
  }

  function closeDiscover() {
    els.discoverOverlay.hidden = true;
  }

  PREFECTURES.forEach((pref) => {
    const opt = document.createElement('option');
    opt.value = pref;
    opt.textContent = pref;
    els.discoverPrefSelect.appendChild(opt);
  });

  els.discoverToggleBtn.addEventListener('click', openDiscover);
  els.closeDiscoverBtn.addEventListener('click', closeDiscover);
  els.discoverOverlay.addEventListener('click', (e) => {
    if (e.target === els.discoverOverlay) closeDiscover();
  });
  els.discoverSearchInput.addEventListener('input', () => {
    updateDiscoverFavToggle();
    renderDiscoverList();
  });
  els.discoverFavToggleBtn.addEventListener('click', () => {
    toggleFavoriteGroup(els.discoverSearchInput.value.trim());
    updateDiscoverFavToggle();
    renderDiscoverFavChips();
  });
  els.discoverDateInput.addEventListener('input', () => {
    els.discoverDateClearBtn.hidden = !els.discoverDateInput.value;
    renderDiscoverList();
  });
  els.discoverDateClearBtn.addEventListener('click', () => {
    els.discoverDateInput.value = '';
    els.discoverDateClearBtn.hidden = true;
    renderDiscoverList();
  });
  els.discoverPrefSelect.addEventListener('change', renderDiscoverList);

  render();
})();
