// Independent check of Achilles' duplicate-screenshot audit, run against prod
// Firestore + Storage. Question being answered: how many BYTES are duplicated,
// and why does the in-app collector miss duplicates that hashing finds?
import admin from 'firebase-admin';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const sa = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');
admin.initializeApp({ credential: admin.credential.cert(sa), storageBucket: 'r01-redditx-suicide.firebasestorage.app' });
const db = admin.firestore();
const parse = (d) => { if (!d) return {}; if (typeof d === 'object') return d; try { return JSON.parse(d); } catch { return {}; } };

const parts = await db.collection('participants').get();
const rows = [];
for (const p of parts.docs) {
  const evs = await p.ref.collection('events').where('eventType', '==', 'screenshot').get();
  for (const d of evs.docs) {
    const v = d.data(); const data = parse(v.data);
    rows.push({
      pid: p.id, id: d.id, session: v.sessionId,
      ts: v.timestamp?.toDate?.()?.getTime() ?? 0,
      hash: data.contentHash || null,
      dedup: !!data.dedup,
      parent: data.dedupOfEventId || null,
      fileSize: Number(data.fileSize) || 0,
      // The object that actually backs this event.
      obj: v.screenshotStoragePath || (data.filePath
        ? `screenshots/${p.id}/${v.sessionId}/${String(data.filePath).split('/').pop()}`
        : null),
    });
  }
}
rows.sort((a, b) => a.ts - b.ts);

// Group by content hash -> how many DISTINCT storage objects hold those bytes?
const byHash = new Map();
for (const r of rows) { if (!r.hash) continue;
  if (!byHash.has(r.hash)) byHash.set(r.hash, []);
  byHash.get(r.hash).push(r); }

let dupEvents = 0, wastedObjects = 0, wastedBytes = 0;
let sameSessionMiss = 0, crossSessionMiss = 0;
const examples = [];
for (const [h, list] of byHash) {
  if (list.length < 2) continue;
  dupEvents += list.length - 1;
  const objs = [...new Set(list.map((r) => r.obj).filter(Boolean))];
  if (objs.length > 1) {
    // Same bytes stored under more than one object => reclaimable.
    const sz = list.find((r) => r.fileSize)?.fileSize || 0;
    wastedObjects += objs.length - 1;
    wastedBytes += sz * (objs.length - 1);
    const sessions = new Set(list.map((r) => r.session));
    sessions.size > 1 ? crossSessionMiss++ : sameSessionMiss++;
    if (examples.length < 6) examples.push({
      hash: h.slice(0, 12), events: list.length, distinctObjects: objs.length,
      distinctSessions: sessions.size, bytesEach: sz,
      collectorFlagged: list.filter((r) => r.dedup).length,
      spanHours: +(((list.at(-1).ts - list[0].ts) / 3.6e6)).toFixed(1),
    });
  }
}

const noHash = rows.filter((r) => !r.hash).length;
console.log(JSON.stringify({
  totalEvents: rows.length,
  eventsMissingContentHash: noHash,
  distinctContentHashes: byHash.size,
  duplicateEventsByHash: dupEvents,
  collectorFlaggedDedup: rows.filter((r) => r.dedup).length,
  reclaimableDuplicateObjects: wastedObjects,
  reclaimableBytes: wastedBytes,
  reclaimableMB: +(wastedBytes / 1048576).toFixed(2),
  hashGroupsStoredTwice_crossSession: crossSessionMiss,
  hashGroupsStoredTwice_sameSession: sameSessionMiss,
}, null, 2));
console.log('\nEXAMPLES'); examples.forEach((e) => console.log(JSON.stringify(e)));
process.exit(0);
