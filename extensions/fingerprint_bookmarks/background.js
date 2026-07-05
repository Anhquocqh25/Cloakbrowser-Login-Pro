async function loadConfig() {
  const response = await fetch(chrome.runtime.getURL("bookmarks.json"), { cache: "no-store" });
  return response.json();
}

async function findBookmarksBar() {
  const tree = await chrome.bookmarks.getTree();
  const roots = tree[0]?.children || [];
  return roots.find(node => node.folderType === "bookmarks-bar") || roots[0];
}

async function ensureFolder(bookmarkBar, folderName) {
  const children = await chrome.bookmarks.getChildren(bookmarkBar.id);
  let folder = children.find(node => !node.url && node.title === folderName);
  if (!folder) folder = await chrome.bookmarks.create({ parentId: bookmarkBar.id, title: folderName });
  return folder;
}

async function syncFolder(folder, desiredItems) {
  const existing = await chrome.bookmarks.getChildren(folder.id);
  const desiredUrls = new Set(desiredItems.map(item => item.url));

  for (const node of existing) {
    if (node.url && !desiredUrls.has(node.url)) await chrome.bookmarks.remove(node.id);
  }

  const refreshed = await chrome.bookmarks.getChildren(folder.id);
  for (const item of desiredItems) {
    const matches = refreshed.filter(node => node.url === item.url);
    if (matches.length === 0) {
      await chrome.bookmarks.create({ parentId: folder.id, title: item.title, url: item.url });
    } else {
      if (matches[0].title !== item.title) await chrome.bookmarks.update(matches[0].id, { title: item.title });
      for (const duplicate of matches.slice(1)) await chrome.bookmarks.remove(duplicate.id);
    }
  }
}

async function ensureManagedBookmarks() {
  const config = await loadConfig();
  const bookmarkBar = await findBookmarksBar();
  if (!bookmarkBar) return;
  for (const folderName of config.folders || []) {
    const folder = await ensureFolder(bookmarkBar, folderName);
    const items = (config.items || []).filter(item => item.folder === folderName);
    await syncFolder(folder, items);
  }
}

let currentRun = null;
function scheduleBookmarkSetup() {
  if (!currentRun) currentRun = ensureManagedBookmarks().finally(() => { currentRun = null; });
  return currentRun;
}

async function ensureProfileGroup(windowId) {
  const config = await loadConfig();
  const profileName = String(config.profileName || "").trim().slice(0, 32);
  if (!profileName) return;

  const tabs = await chrome.tabs.query({ windowId });
  const candidates = tabs.filter(tab => !tab.pinned && Number.isInteger(tab.id));
  if (!candidates.length) return;

  const existingGroup = candidates.find(tab => tab.groupId >= 0)?.groupId;
  const tabIds = candidates.map(tab => tab.id);
  const groupId = existingGroup >= 0
    ? await chrome.tabs.group({ groupId: existingGroup, tabIds })
    : await chrome.tabs.group({ createProperties: { windowId }, tabIds });
  await chrome.tabGroups.update(groupId, {
    title: profileName,
    color: "green",
    collapsed: false,
  });
}

async function ensureAllProfileGroups() {
  const windows = await chrome.windows.getAll({ windowTypes: ["normal"] });
  await Promise.all(windows.map(window => ensureProfileGroup(window.id).catch(() => {})));
}

chrome.runtime.onInstalled.addListener(() => {
  scheduleBookmarkSetup();
  ensureAllProfileGroups();
});
chrome.runtime.onStartup.addListener(() => {
  scheduleBookmarkSetup();
  ensureAllProfileGroups();
});
chrome.tabs.onCreated.addListener(tab => {
  if (Number.isInteger(tab.windowId)) {
    setTimeout(() => ensureProfileGroup(tab.windowId).catch(() => {}), 250);
  }
});
chrome.windows.onCreated.addListener(window => {
  if (Number.isInteger(window.id)) {
    setTimeout(() => ensureProfileGroup(window.id).catch(() => {}), 400);
  }
});
