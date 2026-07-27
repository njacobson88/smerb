// Investigate duplicate screenshot events (Achilles' audit, 2026-07).
// Hypothesis: a "dedup" event reuses the parent's local filePath, but the
// Storage object path is screenshots/{pid}/{SESSION}/{filename} — so when the
// dedup event lands in a DIFFERENT session than its parent, the same bytes get
// uploaded again under a new object ("duplicate with its own file"), whereas a
// same-session dedup hits the URL cache and shares the parent object.
import admin from 'firebase-admin';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');

admin.initializeApp({ credential: admin.credential.cert(serviceAccount) });
const db = admin.firestore();
const PREFIX = process.env.ENVIRONMENT === 'dev' ? 'dev_' : '';

const parse = (d) => {
  if (!d) return {};
  if (typeof d === 'object') return d;
  try { return JSON.parse(d); } catch { return {}; }
};

const run = async () => {
  const parts = await db.collection(`${PREFIX}participants`).get();
  let totals = { events: 0, dedup: 0, sameSession: 0, crossSession: 0, missingParent: 0 };
  const examples = [];

  for (const p of parts.docs) {
    const evs = await p.ref.collection('events').where('eventType', '==', 'screenshot').get();
    if (evs.empty) continue;

    const byId = new Map();
    evs.docs.forEach((d) => byId.set(d.id, d));
    totals.events += evs.size;

    for (const d of evs.docs) {
      const data = parse(d.data().data);
      if (!data.dedup) continue;
      totals.dedup++;
      const parentId = data.dedupOfEventId;
      const parent = parentId ? byId.get(parentId) : null;
      if (!parent) { totals.missingParent++; continue; }

      const sameSession = parent.data().sessionId === d.data().sessionId;
      sameSession ? totals.sameSession++ : totals.crossSession++;

      if (examples.length < 12) {
        examples.push({
          participant: p.id,
          dupEvent: d.id,
          parentEvent: parentId,
          sameSession,
          dupSession: d.data().sessionId,
          parentSession: parent.data().sessionId,
          sharedFile: (data.filePath || '').split('/').pop(),
          dupUrl: (d.data().screenshotUrl || '').split('/').slice(-1)[0]?.slice(0, 60),
          parentUrl: (parent.data().screenshotUrl || '').split('/').slice(-1)[0]?.slice(0, 60),
          sameStorageUrl: d.data().screenshotUrl === parent.data().screenshotUrl,
        });
      }
    }
  }

  console.log('TOTALS', JSON.stringify(totals, null, 2));
  console.log('\nEXAMPLES');
  examples.forEach((e) => console.log(JSON.stringify(e)));
  process.exit(0);
};

run().catch((e) => { console.error(e); process.exit(1); });
