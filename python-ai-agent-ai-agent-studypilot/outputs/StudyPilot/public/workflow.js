"use strict";
// Pure view helpers; this module never saves learning data.
window.StudyWorkflow = (() => {
  const writes = new Map();
  const signature = (path, body) => path + "\n" + JSON.stringify(body);
  function retryKey(path, body) {
    const key = signature(path, body);
    if (!writes.has(key)) {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      writes.set(key, Array.from(bytes, value => value.toString(16).padStart(2, "0")).join(""));
    }
    return writes.get(key);
  }
  function complete(path, body) { writes.delete(signature(path, body)); }
  function clear() { writes.clear(); }
  function nextAction(state, today) {
    const tasks = new Map(state.tasks.filter(t => !t.deleted_at && t.status !== "已完成").map(t => [t.id, t]));
    const entries = state.plans.flatMap(p => p.payload.entries).filter(e => e.date >= today).sort((a, b) => a.date.localeCompare(b.date));
    const logged = new Map();
    state.records.forEach(r => {const key=r.task_id+":"+r.study_date;logged.set(key,(logged.get(key)||0)+r.minutes);});
    for (const entry of entries) {
      const task = tasks.get(entry.task_id);
      if (!task || entry.date > task.due_date || (state.profile.goal_deadline && entry.date > state.profile.goal_deadline)) continue;
      const key = entry.task_id+":"+entry.date, covered = Math.min(logged.get(key)||0,entry.minutes);
      logged.set(key,(logged.get(key)||0)-covered);
      if (entry.minutes > covered) return {...entry,title:task.title,notes:task.notes,minutes:entry.minutes-covered};
    }
    return null;
  }
  return {retryKey,complete,clear,nextAction};
})();
